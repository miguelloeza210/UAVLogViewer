from pydantic import BaseModel

class ChatMessage(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str

class UploadResponse(BaseModel):
    message: str
    filename: str
    log_id: str | None = None
