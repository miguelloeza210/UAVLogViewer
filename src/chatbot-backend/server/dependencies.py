import structlog
from fastapi import HTTPException
from typing import Any
import duckdb

from server.gemini_helper import GeminiClient
from server.duckdb_manager import DuckDBManager


logger = structlog.get_logger()
duckdb_manager = DuckDBManager()


gemini_client = GeminiClient()

class AppState:
    """Simple class to hold application state."""
    def __init__(self):
        self.active_log_id: str | None = None
        self.log_filename: str | None = None      
        self.conversation_history: list[dict[str, any]] = [] 
        self.current_system_instruction: str | None = None

    def reset(self):
        """Resets the state, typically when a new log is uploaded."""
        self.active_log_id = None
        self.log_filename = None
        self.conversation_history = []
        self.current_system_instruction = None
        logger.info("app_state_reset")

app_state = AppState()

def get_app_state() -> AppState:
    """Dependency function to get the shared AppState instance."""
    return app_state

def get_duckdb_conn() -> duckdb.DuckDBPyConnection | None:
    """Dependency function to get the DuckDB connection."""
    conn = duckdb_manager.get_connection()
    if conn is None:
        logger.error("duckdb_connection_not_available_dependency")
    return conn

def get_llm_model():
    """Dependency function to get the initialized LLM model."""
    model = gemini_client.get_model(system_instruction=app_state.current_system_instruction)
    
    if not model:
        logger.error("llm_model_not_available_or_creation_failed", model_name=gemini_client.model_name)
        raise HTTPException(status_code=503, detail="LLM service is not configured or available.")
    return model