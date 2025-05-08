from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware 
from server.chatbot_backend import chatbot_router
import structlog
import logging
import sys


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
# CORS
origins = [
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"], 
)


app.include_router(chatbot_router)

if __name__ == "__main__":
    import uvicorn
    logger.info("uvicorn_startup_direct", host="0.0.0.0", port=8000, reload=True)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)