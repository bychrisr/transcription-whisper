from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TranscriptionCreate(BaseModel):
    filename: str
    file_size: Optional[int] = None
    duration: Optional[float] = None

class TranscriptionResponse(BaseModel):
    id: str
    filename: str
    status: str  # pending, processing, completed, failed
    created_at: datetime
    completed_at: Optional[datetime] = None
    output_file: Optional[str] = None
    error_message: Optional[str] = None
    
    class Config:
        from_attributes = True

class TranscriptionTask(BaseModel):
    task_id: str
    status: str
    progress: Optional[float] = None
    message: Optional[str] = None