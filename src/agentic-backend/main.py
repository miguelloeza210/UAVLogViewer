from fastapi import FastAPI
from server.chatbot_backend import chatbot_router
import structlog
import logging
import sys

# Configure structlog globally for the application
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer() 
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

app = FastAPI(
    title="UAV Log Viewer Agentic Chatbot Backend",
    description="API for uploading UAV logs and chatting about them using an LLM.",
    version="0.1.0",
)

app.include_router(chatbot_router)


# --- Uvicorn Runner (for local development) ---
# This allows running the script directly `python main.py`
# However, using `uvicorn main:app --reload` is generally preferred for development.
if __name__ == "__main__":
    import uvicorn
    logger.info("uvicorn_startup_direct", host="0.0.0.0", port=8000, reload=True)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)