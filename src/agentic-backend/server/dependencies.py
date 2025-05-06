import structlog
from fastapi import HTTPException
from typing import Any

from server.gemini_helper import GeminiClient

logger = structlog.get_logger()

gemini_client = GeminiClient()


class AppState:
    """Simple class to hold application state."""
    def __init__(self):
        self.log_data: dict[str, Any] | None = None 
        self.log_filename: str | None = None      
        self.conversation_history: list[tuple[str, str]] = []

    def reset(self):
        """Resets the state, typically when a new log is uploaded."""
        self.log_data = None
        self.log_filename = None
        self.conversation_history = []
        logger.info("app_state_reset")

app_state = AppState()

def get_app_state() -> AppState:
    """Dependency function to get the shared AppState instance."""
    return app_state


def get_llm_model():
    """Dependency function to get the initialized LLM model."""
    model = gemini_client.get_model()
    if not model:
        # Log the model name used during initialization attempt
        logger.error("llm_model_not_available", model_name=gemini_client.model_name)
        raise HTTPException(status_code=503, detail="LLM service is not configured or available.")
    return model