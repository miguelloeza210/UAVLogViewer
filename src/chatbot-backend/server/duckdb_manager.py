import duckdb
import structlog

logger = structlog.get_logger()

class DuckDBManager:
    def __init__(self, database_path: str = ':memory:'):
        self.connection: duckdb.DuckDBPyConnection | None = None
        try:
            self.connection = duckdb.connect(database=database_path, read_only=False)
            logger.info("duckdb_connection_established", database_path=database_path)
        except Exception as e:
            logger.error("duckdb_connection_failed_on_init", database_path=database_path, error=str(e), exc_info=True)
            self.connection = None

    def __del__(self):
        self.close_connection()

    def get_connection(self) -> duckdb.DuckDBPyConnection | None:
        return self.connection

    def close_connection(self):
        if self.connection:
            self.connection.close()
            logger.info("duckdb_connection_closed")

def drop_tables_for_log_id(conn: duckdb.DuckDBPyConnection, log_id: str):
    """Drops all tables associated with a given log_id."""
    if not conn or not log_id:
        return
    try:
        tables = conn.execute(f"SELECT table_name FROM information_schema.tables WHERE table_name LIKE '{log_id}_%'").fetchall()
        for table_name_tuple in tables:
            table_name = table_name_tuple[0]
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            logger.info("duckdb_table_dropped_via_manager", table_name=table_name, log_id=log_id)
    except Exception as e:
        logger.error("duckdb_error_dropping_tables_via_manager", log_id=log_id, error=str(e), exc_info=True)