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
        """
        Initializes the Gemini client.

        Args:
            model_name (str): The name of the Gemini model to use.
                              Defaults to 'gemini-1.5-flash'.
        """
        load_dotenv()
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.model = None # Initialize model attribute

        if not self.api_key:
            logger.error("gemini_api_key_missing", error="GEMINI_API_KEY not found in environment variables.")
            # Consider whether to raise an error or allow the app to run without LLM features
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        else:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
                logger.info("gemini_client_initialized", model_name=self.model_name)
            except Exception as e:
                logger.error("gemini_client_initialization_failed", model_name=self.model_name, error=str(e), exc_info=True)
                self.model = None

    def get_model(self):
        """Returns the initialized GenerativeModel instance."""
        return self.model