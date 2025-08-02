from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

# Configurar logging
logging.basicConfig(level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')))
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Whisper Enterprise API",
    description="Sistema robusto de transcrição automatizada",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Whisper Enterprise API", "status": "running"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "whisper-api",
        "timestamp": __import__('datetime').datetime.utcnow().isoformat()
    }

# Configuração do Celery
from celery import Celery

celery = Celery(__name__)
celery.conf.broker_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
celery.conf.result_backend = os.getenv('REDIS_URL', 'redis://localhost:6379')