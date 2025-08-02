import os
from typing import Optional

class Settings:
    PROJECT_NAME: str = "Whisper Enterprise"
    PROJECT_VERSION: str = "1.0.0"
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    TELEGRAM_TOKEN: Optional[str] = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
    
    SECRET_KEY: str = os.getenv("SECRET_KEY", "secret-key-for-development")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Diretórios de dados
    INPUT_DIR: str = "/app/data/input"
    INPUT_WEB_DIR: str = "/app/data/input_web"
    OUTPUT_DIR: str = "/app/data/output"
    OUTPUT_PARTS_DIR: str = "/app/data/output_parts"
    LOGS_DIR: str = "/app/data/logs"

settings = Settings()