from dotenv import load_dotenv
import os
import google.generativeai as genai
import structlog

logger = structlog.get_logger()

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")

class GeminiClient:
    """
    Handles the configuration and initialization of the Google Gemini client.
    """
    def __init__(self, model_name: str = GEMINI_MODEL_NAME):
        """Initializes the Gemini client."""
        load_dotenv()
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = model_name

        if not self.api_key:
            logger.error("gemini_api_key_missing", error="GEMINI_API_KEY not found in environment variables.")
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        else:
            try:
                genai.configure(api_key=self.api_key)
                logger.info("gemini_client_configured_for_model", model_name=self.model_name)
            except Exception as e:
                logger.error("gemini_client_initialization_failed", model_name=self.model_name, error=str(e), exc_info=True)

    def get_model(self, system_instruction: str | None = None) -> genai.GenerativeModel | None:
        """Returns a new GenerativeModel instance, optionally configured with a system instruction."""
        if not self.api_key:
            logger.error("gemini_api_key_not_configured_at_get_model")
            return None
        try:
            model_instance = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction
            )
            logger.info("gemini_model_instance_created", model_name=self.model_name, has_system_instruction=bool(system_instruction))
            return model_instance
        except Exception as e:
            logger.error("gemini_model_creation_failed", model_name=self.model_name, error=str(e), exc_info=True)
            return None