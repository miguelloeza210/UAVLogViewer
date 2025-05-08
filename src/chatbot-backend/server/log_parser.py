from pymavlink import mavutil
import structlog
import pandas as pd
import typing
import os
import tempfile
import shutil
import duckdb

logger = structlog.get_logger()

def parse_and_store_log(original_file_obj: typing.IO[bytes], 
                        original_filename: str,
                        db_conn: duckdb.DuckDBPyConnection,
                        log_id: str) -> dict:
    """
    Parses a MAVLink log file (e.g., .bin, .tlog) and extracts all messages
    into separate tables in DuckDB, one for each MAVLink message type.
    It writes the input file object to a temporary file on disk for robust parsing
    with pymavlink.

    Args:
        original_file_obj: A file-like object opened in binary mode (e.g., UploadFile.file).
        original_filename: The original name of the uploaded file.
        db_conn: An active DuckDB connection.
        log_id: A unique identifier for this log file session.
    Returns:
        A dictionary containing the status of the operation, list of created tables,
        and counts of parsed/stored messages.
    """
    messages = []
    temp_file_path = None

    try:
        if hasattr(original_file_obj, 'seek'):
            original_file_obj.seek(0)

        _, suffix = os.path.splitext(original_filename)
        if not suffix:
            suffix = ".log"
            logger.debug("log_parser_no_suffix_defaulting", original_filename=original_filename, using_suffix=suffix)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='wb') as temp_f:
            shutil.copyfileobj(original_file_obj, temp_f)
            temp_file_path = temp_f.name
        
        logger.debug("log_parser_using_temp_file", path=temp_file_path, original_filename=original_filename)

        mlog = mavutil.mavlink_connection(temp_file_path, robust_parsing=True)

        while True:
            msg = mlog.recv_match()
            if msg is None:
                break
            
            if msg.get_type() == 'BAD_DATA':
                continue
            messages.append(msg.to_dict())
        
        if not messages:
            logger.info("log_parser_no_messages_found", file_path=temp_file_path, original_filename=original_filename)
            return {"status": "no_messages_parsed", "log_id": log_id, "tables_created": [], "total_messages_parsed": 0, "total_rows_stored": 0}

        df = pd.DataFrame(messages)
        logger.info("log_parser_success", num_messages_parsed=len(df), file_path=temp_file_path, original_filename=original_filename)
        if df.empty:
            logger.info("log_parser_empty_dataframe_after_parsing", log_id=log_id, original_filename=original_filename)
            return {"status": "no_data_to_store", "log_id": log_id, "tables_created": [], "total_messages_parsed": 0, "total_rows_stored": 0}

        if 'mavpackettype' not in df.columns:
            logger.error("log_parser_missing_mavpackettype_column", log_id=log_id, columns=df.columns.tolist())
            return {"status": "error", "message": "mavpackettype column missing in parsed data", "log_id": log_id}

        created_tables = []
        total_rows_stored = 0

        for msg_type, group_df in df.groupby('mavpackettype'):
            if group_df.empty:
                continue
            
            # Sanitize table name slightly, though mavpackettype is usually safe
            table_name = f"{msg_type.replace('-', '_').replace('.', '_')}" 
            
            quoted_view_name = f"df_view_{table_name}"
            try:
                logger.debug(f"Attempting to register view: \"{quoted_view_name}\" for msg_type: {msg_type}")
                db_conn.register(quoted_view_name, group_df)
            

                logger.debug(f"Attempting to create table: \"{table_name}\" from view \"{quoted_view_name}\"")
                db_conn.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM "{quoted_view_name}"')
                db_conn.unregister(quoted_view_name)
                
                created_tables.append(table_name)
                total_rows_stored += len(group_df)
                logger.debug("duckdb_table_created_from_log", table_name=table_name, log_id=log_id, num_rows=len(group_df))
            except Exception as e_db:
                logger.error("duckdb_table_creation_failed", table_name=table_name, log_id=log_id, error=str(e_db), exc_info=True)

        if not created_tables:
            logger.warning("log_parser_no_tables_created_in_db", log_id=log_id, total_messages_parsed=len(df))
            return {"status": "no_tables_stored", "log_id": log_id, "tables_created": [], "total_messages_parsed": len(df), "total_rows_stored": 0}

        logger.info("log_parser_storage_success", log_id=log_id, num_tables=len(created_tables), total_rows_stored=total_rows_stored, original_filename=original_filename)
        return {
            "status": "success",
            "log_id": log_id,
            "tables_created": created_tables,
            "total_messages_parsed": len(df),
            "total_rows_stored": total_rows_stored
        }

    except Exception as e:
        log_context = {"original_filename": original_filename, "file_object_info": str(original_file_obj)}
        if temp_file_path:
            log_context["temp_file_path_at_error"] = temp_file_path
        logger.error("log_parser_failed", error=str(e), **log_context, exc_info=True)
        return {"status": "error", "message": str(e), "log_id": log_id if 'log_id' in locals() else None}
    finally:
        if temp_file_path:
            try:
                os.remove(temp_file_path)
                logger.debug("temp_log_file_deleted", path=temp_file_path)
            except OSError as e_os:
                logger.warning("temp_log_file_deletion_failed", path=temp_file_path, error=str(e_os))