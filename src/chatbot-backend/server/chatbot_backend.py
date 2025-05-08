import structlog
import uuid
import duckdb

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends

from server.models import ChatMessage, ChatResponse, UploadResponse
from google.generativeai.types import GenerationConfig
from server.dependencies import get_app_state, get_llm_model, get_duckdb_conn, AppState
from server.log_parser import parse_and_store_log
from server.duckdb_manager import drop_tables_for_log_id

logger = structlog.get_logger()

chatbot_router = APIRouter(prefix='/api', tags=['api'])


@chatbot_router.post("/upload_log/", response_model=UploadResponse)
async def upload_log_file(
    file: UploadFile = File(...),
    app_state: AppState = Depends(get_app_state),
    db_conn: duckdb.DuckDBPyConnection | None = Depends(get_duckdb_conn)
):
    """ Accepts a .bin log file, parses it, and stores the data. """
    allowed_extensions = (".bin", ".tlog", ".log", ".px4log", ".ulg")
    
    if not file.filename.lower().endswith(allowed_extensions):
        logger.warning("invalid_file_type_uploaded", filename=file.filename)
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}")

    app_state.reset()
    if app_state.active_log_id and db_conn:
        logger.info("attempting_to_drop_tables_for_old_log", old_log_id=app_state.active_log_id)
        drop_tables_for_log_id(db_conn, app_state.active_log_id)

    new_log_id = str(uuid.uuid4())
    app_state.active_log_id = new_log_id
    app_state.log_filename = file.filename

    logger.info("processing_new_log_upload", filename=file.filename, new_log_id=new_log_id)
    parse_result = parse_and_store_log(
        original_file_obj=file.file, 
        original_filename=file.filename,
        db_conn=db_conn,
        log_id=new_log_id
    )

    if parse_result.get("status") != "success":
        logger.error("log_parsing_and_storage_failed", filename=file.filename, log_id=new_log_id, result=parse_result)
        app_state.reset()
        raise HTTPException(status_code=500, detail=f"Failed to process log file: {parse_result.get('message', 'Unknown error')}")

    data_schema_summary = ""
    if db_conn and new_log_id:
        try:
            tables_query = f"SELECT table_name FROM information_schema.tables WHERE table_name LIKE '{new_log_id}_%'"
            tables_result = db_conn.execute(tables_query).fetchall()
            
            if tables_result:
                schema_lines = ["Available MAVLink message tables and their columns:"]
                for table_tuple in tables_result:
                    full_table_name = table_tuple[0]
                    clean_table_name = full_table_name.replace(f"{new_log_id}_", "", 1)
                    
                    columns_query = f"PRAGMA table_info('{full_table_name}')"
                    columns_result = db_conn.execute(columns_query).fetchall()
                    column_names = [col[1] for col in columns_result]
                    
                    schema_lines.append(f"- {clean_table_name}: {', '.join(column_names)}")
                
                data_schema_summary = "\n".join(schema_lines)
        except Exception as e_schema:
            logger.error("failed_to_generate_schema_summary_for_llm", log_id=new_log_id, error=str(e_schema), exc_info=True)
            data_schema_summary = "Could not retrieve data schema information for the log file."


    base_system_prompt = f"""
    You are a flight telemetry analysis assistant trained to understand and reason about parsed MAVLink logs. 
    Your primary role is to help users investigate flight data in a conversational and analytical manner.
    If telemetry is missing, incomplete, or ambiguous, explain the limitation clearly and suggest what additional data would be needed. Do not fabricate information. If you infer something, explain your reasoning.
    {data_schema_summary}
    Use these tables and columns to understand the available data. Assume data conforms to MAVLink's common message format as defined at: https://mavlink.io/en/messages/common.html
    You may query the database using the format: QUERY DB:<Your query here>\n. If an answer cannot be resolved after 3 queries, inform the user. Be careful with how much data you are requesting. Use minimal queries wherever possible.
    You have access to structured telemetry such as: altitude, GPS signal quality, flight mode, battery status, RC input, servo outputs, IMU readings, system status, and mission data. Use this data to answer questions about flight behavior, performance, and anomalies.
    MAVLink reference:
    HEARTBEAT includes custom_mode (flight mode) and system_status; custom_mode must be interpreted per autopilot type.
    SYSTEM_TIME provides time_unix_usec (UTC) and time_boot_ms (uptime).
    GPS_RAW_INT and GPS2_RAW offer fix_type, eph, and satellites_visible; use GPS2_RAW if dual GPS is active.
    ATTITUDE reports roll, pitch, and yaw in radians.
    GLOBAL_POSITION_INT includes latitude and longitude (scaled by 1e7), alt (AMSL), relative_alt (takeoff-relative), heading (hdg), and ground speed.
    LOCAL_POSITION_NED provides local x, y, z coordinates and velocities; z is typically negative as altitude increases.
    ALTITUDE adds terrain-relative height and AGL, if supported.
    HOME_POSITION specifies home coordinates.
    MISSION_ITEM_INT defines mission waypoints; MISSION_CURRENT shows the active waypoint index; MISSION_ACK reports mission upload success or failure.
    BATTERY_STATUS includes voltages per cell, current_battery, and battery_remaining.
    SYS_STATUS may also report battery health.
    POWER_STATUS includes Vcc and Vservo (PX4 systems only).
    RC_CHANNELS and RC_CHANNELS_RAW show control inputs (usually 1000 and 2000 µs).
    SERVO_OUTPUT_RAW shows actuator outputs in PWM.
    RAW_IMU, SCALED_IMU2, and SCALED_IMU3 contain raw sensor readings.
    SCALED_PRESSURE messages contain barometric pressure and temperature.
    VIBRATION indicates axis-specific vibrations and sensor clipping.
    STATUSTEXT gives human-readable logs and warnings with severity level.
    COMMAND_ACK confirms command results.
    PARAM_VALUE provides parameter names and values.
    Behavior:
    Maintain conversation state across turns.
    Respond precisely and clearly using available telemetry.
    Before answering questions, check to the tables to see if you have what you need. If the table is empty or the data is bad, say you cannot answer the question.
    Ask clarifying questions when needed.
    Be concise in your responses.
    When asked about anomalies, look for sudden changes in altitude, GPS inconsistency, battery overheating, RC dropout, STATUSTEXT errors, or mode changes. Start by constructing a query that you would like to run.
    """

    app_state.current_system_instruction = base_system_prompt
    logger.info("system_instruction_set_for_llm", log_id=new_log_id, filename=file.filename)
    return UploadResponse(message="Log file uploaded, parsed, and stored successfully.", filename=app_state.log_filename, log_id=new_log_id)


@chatbot_router.post("/chat/", response_model=ChatResponse)
async def chat_endpoint(
    chat_message: ChatMessage,
    app_state: AppState = Depends(get_app_state),
    llm_model = Depends(get_llm_model),
    db_conn: duckdb.DuckDBPyConnection | None = Depends(get_duckdb_conn)
):
    """ Handles user queries about the currently loaded log file. """
    user_query = chat_message.message
    try:
        generation_config = GenerationConfig(
            temperature=0.3,
            top_p=0.9,
            top_k=40,
        )
        
        if not app_state.active_log_id or not app_state.current_system_instruction:
            logger.warning("chat_attempt_with_no_active_log_or_system_instruction")
            raise HTTPException(status_code=400, detail="No log file is currently active or system prompt not set. Please upload a log first.")

        initial_messages_for_llm = []
        MAX_HISTORY_MESSAGES_TO_SEND = 10
        if app_state.conversation_history:
            start_index = max(0, len(app_state.conversation_history) - MAX_HISTORY_MESSAGES_TO_SEND)
            initial_messages_for_llm.extend(app_state.conversation_history[start_index:])
            if start_index > 0:
                logger.info("conversation_history_truncated_for_llm_input", original_length=len(app_state.conversation_history), sent_length=MAX_HISTORY_MESSAGES_TO_SEND)
        initial_messages_for_llm.append({"role": "user", "parts": [user_query]})

        # This list will hold messages specifically for the current turn, especially within the DB query loop
        current_turn_messages = list(initial_messages_for_llm) 
        # Limit the number of DB query attempts
        db_query_attempts = 0
        max_db_query_attempts = 3

        while db_query_attempts < max_db_query_attempts:
            response = await llm_model.generate_content_async(
                contents=current_turn_messages, 
                generation_config=generation_config
            )
            print(response)
            bot_response_text = response.text
            logger.info("llm_response_received", attempt=db_query_attempts + 1, response_preview=f"{bot_response_text[:200]}...")
            if "QUERY DB:" in bot_response_text:
                db_query_attempts += 1
                try:
                    query_marker = "QUERY DB:"
                    query_start_index = bot_response_text.find(query_marker)
                    potential_query_block = bot_response_text[query_start_index + len(query_marker):].strip()
                    sql_query = potential_query_block.split('\n')[0].strip()
                    print("sql: ", sql_query)
                    logger.info("extracted_sql_query", query=sql_query)
                    query_results = db_conn.execute(sql_query).fetchall()
                    print(query_results)
                    logger.info("db_query_successful", results_preview=str(query_results)[:200])

                    message_with_db_results = f"Here are the results to your query ('{sql_query}'): {query_results}. Now, using these results, please answer the original user query: '{user_query}'"
                    current_turn_messages.append({"role": "user", "parts": [message_with_db_results]}) 

                except Exception as db_error:
                    logger.error("db_query_execution_error", query=sql_query if 'sql_query' in locals() else "unknown_query", error=str(db_error), exc_info=True)
                    error_feedback_to_llm = f"You tried to execute the SQL query: '{sql_query if 'sql_query' in locals() else 'previous query attempt'}'. It failed with the following error: {str(db_error)}. Please analyze this error, correct your SQL query, and try again using the 'QUERY DB:' prefix."
                    current_turn_messages.append({"role": "user", "parts": [error_feedback_to_llm]}) 
            else:
                break
        else:
            if "QUERY DB:" in bot_response_text:
                logger.warning("max_db_query_attempts_reached_llm_still_trying_to_query", log_id=app_state.active_log_id)
                bot_response_text = "I tried to query the database multiple times but could not retrieve the information needed to answer your question. Please try rephrasing or ask something different."

        app_state.conversation_history.append({"role": "user", "parts": [user_query]})
        app_state.conversation_history.append({"role": "model", "parts": [bot_response_text]})

    except Exception as e:
        logger.error("llm_interaction_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error communicating with LLM: {str(e)}")
    return ChatResponse(response=bot_response_text)