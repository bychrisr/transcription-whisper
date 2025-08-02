from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import os

from app.core.config import settings
from app.api.v1.api import api_router

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

# Incluir rotas da API
app.include_router(api_router)

# Montar diretório de arquivos transcritos
app.mount("/output", StaticFiles(directory=settings.OUTPUT_DIR), name="output")

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
celery.conf.broker_url = settings.REDIS_URL
celery.conf.result_backend = settings.REDIS_URL