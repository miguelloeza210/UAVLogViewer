import os
import shutil
import structlog
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends

# Import state and LLM dependencies
from server.models import ChatMessage, ChatResponse, UploadResponse
from server.dependencies import get_app_state, get_llm_model, AppState
from server.log_parser import parse_log

logger = structlog.get_logger()

chatbot_router = APIRouter(prefix='/api/', tags=['api'])


@chatbot_router.post("/upload_log/", response_model=UploadResponse)
async def upload_log_file(
    file: UploadFile = File(...),
    app_state: AppState = Depends(get_app_state) # Inject state
):
    """ Accepts a .bin log file, parses it, and stores the data. """

    if not file.filename.lower().endswith(".bin"):
        logger.warning("invalid_file_type_uploaded", filename=file.filename)
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .bin file.")

    # Use tempfile for safer handling of temporary files
    try:
        # Create a temporary file to store the upload
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_file_path = temp_file.name # Get the path to the temp file
        logger.info("log_file_saved_temporarily", temp_path=temp_file_path, original_filename=file.filename)

        # Parse the log using the temporary file path
        parsed_data = parse_log(temp_file_path)

        # Update the application state
        app_state.reset() # Clear previous state first
        app_state.log_data = parsed_data
        app_state.log_filename = file.filename
        logger.info("log_parsed_successfully", filename=app_state.log_filename)

        return UploadResponse(message="Log file uploaded and parsed successfully.", filename=app_state.log_filename)

    except Exception as e:
        logger.error("log_processing_failed", filename=file.filename, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process log file: {str(e)}")
    finally:
        # Ensure the uploaded file object is closed
        await file.close()
        # Clean up the temporary file if it still exists
        if 'temp_file_path' in locals() and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info("temporary_log_file_removed", temp_path=temp_file_path)
            except OSError as remove_error:
                logger.error("temporary_log_file_remove_failed", temp_path=temp_file_path, error=str(remove_error))


@chatbot_router.post("/chat/", response_model=ChatResponse)
async def chat_endpoint(
    chat_message: ChatMessage,
    app_state: AppState = Depends(get_app_state), # Inject state
    llm_model = Depends(get_llm_model) # Inject the LLM model
):
    """ Handles user queries about the currently loaded log file. """

    if app_state.log_data is None or app_state.log_filename is None:
        raise HTTPException(status_code=400, detail="No log file has been uploaded and parsed yet. Please upload a .bin file first via /upload_log/.")


    user_query = chat_message.message
    log = logger.bind(query=user_query, log_filename=app_state.log_filename) # Bind context
    log.info("chat_query_received")

    # --- TODO: Implement LLM Interaction ---
    # 1. Data Retrieval: Extract relevant data snippets from CURRENT_LOG_DATA based on the query.
    #    (e.g., max altitude, specific errors, GPS status changes)
    # 2. Prompt Construction: Create a prompt for Gemini including:
    #    - System instructions (role, capabilities, limitations)
    #    - Conversation history (CONVERSATION_HISTORY)
    #    - The user's current query (user_query)
    #    - Relevant data snippets retrieved in step 1.
    # 3. LLM Call: Send the prompt to the Gemini API (llm_model.generate_content(...)).
    #    Handle potential API errors.
    # 4. Response Processing: Extract the text response from the Gemini result.
    # 5. History Update: Append the user query and the bot's response to CONVERSATION_HISTORY.
    #    Consider limiting history size.

    # --- Placeholder Logic ---
    try:
        # Example: Construct a very basic prompt (replace with sophisticated logic)
        prompt = f"""You are analyzing flight log data for the file '{app_state.log_filename}'.
        The log duration is {app_state.log_data.get('duration_seconds', 'N/A'):.2f} seconds.
        User query: "{user_query}"
        Provide a concise answer based ONLY on the information given or general knowledge about ArduPilot logs if applicable. If you need specific data not provided here, state that.
        Previous conversation: {app_state.conversation_history}
        """
        # In a real implementation, you'd add specific data here based on query analysis.

        log.debug("llm_prompt_constructed", prompt_preview=f"{prompt[:200]}...")
        response = await llm_model.generate_content_async(prompt) # Use async version
        bot_response_text = response.text
        log.info("llm_response_received", response_preview=f"{bot_response_text[:200]}...")

        # Update history
        app_state.conversation_history.append(("user", user_query))
        app_state.conversation_history.append(("model", bot_response_text))
        # Optional: Limit history size
        # MAX_HISTORY = 10 # Keep last 5 pairs (10 items)
        # if len(app_state.conversation_history) > MAX_HISTORY:
        #     app_state.conversation_history = app_state.conversation_history[-MAX_HISTORY:]

    except Exception as e:
        log.error("llm_interaction_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error communicating with LLM: {str(e)}")
    # --- End Placeholder ---

    return ChatResponse(response=bot_response_text)