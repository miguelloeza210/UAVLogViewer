import structlog
import uuid
import re
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

    # old_log_id = app_state.active_log_id
    # Reset app state for the new log. This clears previous log_id, history, etc.
    app_state.reset() 

    # if old_log_id and db_conn:
    #     logger.info("attempting_to_drop_tables_for_old_log", old_log_id=old_log_id)
    #     drop_tables_for_log_id(db_conn, old_log_id)

    log_id = str(uuid.uuid4())
    app_state.active_log_id = log_id
    app_state.log_filename = file.filename

    logger.info("processing_new_log_upload", filename=file.filename, log_id=log_id)
    parse_result = parse_and_store_log(
        original_file_obj=file.file, 
        original_filename=file.filename,
        db_conn=db_conn,
        log_id=log_id
    )

    if parse_result.get("status") != "success":
        logger.error("log_parsing_and_storage_failed", filename=file.filename, log_id=log_id, result=parse_result)
        app_state.reset()
        raise HTTPException(status_code=500, detail=f"Failed to process log file: {parse_result.get('message', 'Unknown error')}")

    data_schema_summary = ""
    if db_conn:
        try:
            tables_query = f"SELECT table_name FROM information_schema.tables WHERE table_name LIKE '{log_id}_%'"
            tables_result = db_conn.execute(tables_query).fetchall()
            print(tables_result)
            
            if tables_result:
                schema_lines = ["Available MAVLink message tables and their columns:"]
                for table_tuple in tables_result:
                    full_table_name = table_tuple[0]
                    
                    columns_query = f"PRAGMA table_info('{full_table_name}')"
                    columns_result = db_conn.execute(columns_query).fetchall()
                    column_names = [col[1] for col in columns_result]
                    
                    schema_lines.append(f"- {full_table_name}: {', '.join(column_names)}")
                
                data_schema_summary = "\n".join(schema_lines)
        except Exception as e_schema:
            logger.error("failed_to_generate_schema_summary_for_llm", log_id=log_id, error=str(e_schema), exc_info=True)
            data_schema_summary = "Could not retrieve data schema information for the log file."


    base_system_prompt = f"""
    You are a flight telemetry analysis assistant. Your goal is to help users investigate flight data from parsed MAVLink logs.
    You are a ReAct Agent that will answer the user's queries. This involves a Thought-Action-Observation cycle.
    Tools: Tables in a DuckDB database. You may write queries and the results will be retrieved for you.
    Here is the schema: {data_schema_summary}
    Here's how you should operate:
    1. **Thought**: Based on the user's query and previous observations, explain your reasoning and what you need to find out next.
    2. **Action**: Specify the action to take. Currently, the only available action is `query_db`.
    3. **Action Input**: Provide the input for the action. For `query_db`, this is the SQL query. 

    You will receive an **Observation** with the results of your action. Use this observation to continue your thought process.
    Repeat the Thought-Action-Observation cycle until you have enough information to answer the user's original request.

    When you have the final answer, provide it directly without using the Action format. Start your final answer with "Final Answer:".

    Example:
    User: What was the maximum altitude reached?

    Thought: I need to find the maximum altitude. I should look for a table that contains altitude data, like 'GLOBAL_POSITION_INT', and then query the 'alt' column.
    Action: query_db
    Action Input: SELECT MAX(alt) FROM GLOBAL_POSITION_INT
    (System provides Observation)
    Observation: [(85000,)]
    Thought: The maximum altitude was 85000 (likely mm AMSL as per GLOBAL_POSITION_INT.alt). I can now provide this to the user.
    Final Answer: The maximum altitude reached was 85000mm AMSL.

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
    - If telemetry is missing, incomplete, or ambiguous, explain the limitation clearly in your Thought process and Final Answer.
    - Do not fabricate information. If you infer something, explain your reasoning in your Thought.
    - Be careful with how much data you are requesting. Use minimal queries wherever possible.
    - If you find yourself unable to answer after a reasonable number of attempts to gather information, inform the user in your Final Answer.
    When asked about anomalies, look for sudden changes in altitude, GPS inconsistency, battery overheating, RC dropout, STATUSTEXT errors, or mode changes.
    """

    app_state.current_system_instruction = base_system_prompt
    logger.info("system_instruction_set_for_llm", log_id=log_id, filename=file.filename)
    return UploadResponse(message="Log file uploaded, parsed, and stored successfully.", filename=app_state.log_filename, log_id=log_id)


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
            temperature=0.4,
            top_p=0.9,
            top_k=40,
        )
        
        if not app_state.active_log_id or not app_state.current_system_instruction:
            logger.warning("chat_attempt_with_no_active_log_or_system_instruction")
            raise HTTPException(status_code=400, detail="No log file is currently active or system prompt not set. Please upload a log first.")

        if not db_conn:
            logger.error("chat_endpoint_db_connection_missing", log_id=app_state.active_log_id)
            raise HTTPException(status_code=500, detail="Database connection is not available.")
        
        initial_messages_for_llm = []
        MAX_HISTORY_MESSAGES_TO_SEND = 15
        if app_state.conversation_history:
            start_index = max(0, len(app_state.conversation_history) - MAX_HISTORY_MESSAGES_TO_SEND)
            initial_messages_for_llm.extend(app_state.conversation_history[start_index:])
            if start_index > 0:
                logger.info("conversation_history_truncated_for_llm_input", original_length=len(app_state.conversation_history), sent_length=MAX_HISTORY_MESSAGES_TO_SEND)
        initial_messages_for_llm.append({"role": "user", "parts": [user_query]})

        # This list will hold messages specifically for the current turn, especially within the DB query loop
        current_turn_messages = list(initial_messages_for_llm) 
        
        MAX_REACT_STEPS = 10 # Maximum number of ReAct steps (Thought-Action-Observation cycles) per user query
        current_react_step = 0
        bot_response_text = "" # Initialize to store the final answer
        while current_react_step < MAX_REACT_STEPS:
            current_react_step += 1
            response = await llm_model.generate_content_async(
                contents=current_turn_messages, 
                generation_config=generation_config
            )
            llm_output_text = response.text.strip()
            logger.info("llm_raw_response_received", step=current_react_step, response_preview=f"{llm_output_text[:250]}...")

            # Append LLM's raw response to the current turn messages (for its own context if it needs to retry/reflect)
            current_turn_messages.append({"role": "model", "parts": [llm_output_text]})

            thought_match = re.search(r"Thought:(.*?)Action:", llm_output_text, re.DOTALL | re.IGNORECASE)
            action_match = re.search(r"Action:(.*?)(Action Input:|$)", llm_output_text, re.DOTALL | re.IGNORECASE)
            action_input_match = re.search(r"Action Input:(.*)", llm_output_text, re.DOTALL | re.IGNORECASE)
            final_answer_match = re.search(r"Final Answer:(.*)", llm_output_text, re.DOTALL | re.IGNORECASE)

            thought = thought_match.group(1).strip() if thought_match else None
            action_str = action_match.group(1).strip().lower() if action_match else None
            action_input = action_input_match.group(1).strip() if action_input_match else None
            
            if final_answer_match:
                bot_response_text = final_answer_match.group(1).strip()
                logger.info("llm_provided_final_answer", answer_preview=bot_response_text[:200])
                break 

            if action_str and action_input:
                logger.info("llm_action_parsed", thought=thought, action=action_str, action_input_preview=action_input[:100])
                observation_text = ""
                if action_str == "query_db":
                    sql_query = action_input
                    try:
                        logger.info("executing_sql_query_from_llm", query=sql_query)
                        query_results = db_conn.execute(sql_query).fetchall()
                        # Consider truncating large results for observation:
                        # max_obs_length = 1500 
                        # results_str = str(query_results)
                        # if len(results_str) > max_obs_length:
                        #    results_str = results_str[:max_obs_length] + f"... (truncated, {len(query_results)} rows total)"
                        observation_text = f"Observation: Query executed. Results: {str(query_results)}"
                        logger.info("db_query_successful", results_preview=str(query_results)[:200])
                    except Exception as db_error:
                        logger.error("db_query_execution_error", query=sql_query, error=str(db_error), exc_info=True)
                        observation_text = f"Observation: Error executing SQL query '{sql_query}'. Error: {str(db_error)}. Please check your query syntax, ensure the table and column names are correct. Refer to the schema and try again."
                else:
                    logger.warning("llm_unknown_action_requested", action=action_str)
                    observation_text = f"Observation: Unknown action '{action_str}'. The only available action is 'query_db'."
                
                current_turn_messages.append({"role": "user", "parts": [observation_text]})
                logger.debug("observation_fed_back_to_llm", observation_preview=observation_text[:200])
            else:
                bot_response_text = llm_output_text 
                logger.warning("llm_did_not_provide_action_or_final_answer_in_format", response_preview=bot_response_text[:200])
                break
        else:
            if not bot_response_text:
                logger.warning("max_react_steps_reached_without_final_answer", log_id=app_state.active_log_id, steps=current_react_step)
                bot_response_text = "I have taken several steps but haven't reached a final answer. Please try rephrasing your query or ask something more specific."

        app_state.conversation_history.append({"role": "user", "parts": [user_query]})
        app_state.conversation_history.append({"role": "model", "parts": [bot_response_text]})
    except Exception as e:
        logger.error("llm_interaction_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error communicating with LLM: {str(e)}")
    return ChatResponse(response=bot_response_text)