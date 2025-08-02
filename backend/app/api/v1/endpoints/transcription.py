from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import logging
from pathlib import Path
from typing import List
import uuid

from app.core.config import settings
from app.schemas.transcription import TranscriptionCreate, TranscriptionResponse
from app.services.file_service import FileService
from app.workers.transcription_worker import transcribe_audio_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/transcription", tags=["transcription"])

file_service = FileService()

@router.post("/upload/", response_model=dict)
async def upload_audio(file: UploadFile = File(...)):
    """Upload de arquivo de áudio para transcrição"""
    try:
        # Validar tipo de arquivo
        allowed_extensions = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
        if not Path(file.filename).suffix.lower() in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail="Formato de arquivo não suportado"
            )
        
        # Salvar arquivo
        file_path = await file_service.save_upload_file(file)
        
        # Criar task de transcrição
        task_id = str(uuid.uuid4())
        transcribe_audio_task.delay(str(file_path), task_id)
        
        logger.info(f"Arquivo {file.filename} enviado para transcrição. Task ID: {task_id}")
        
        return {
            "task_id": task_id,
            "filename": file.filename,
            "status": "processing",
            "message": "Arquivo recebido e em fila para processamento"
        }
        
    except Exception as e:
        logger.error(f"Erro no upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}", response_model=dict)
async def get_task_status(task_id: str):
    """Obter status de uma task de transcrição"""
    # Implementar lógica de status (por enquanto mock)
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Task em processamento"
    }

@router.get("/files/", response_model=List[dict])
async def list_transcribed_files():
    """Listar arquivos transcritos disponíveis"""
    try:
        files = file_service.list_transcriptions()
        return files
    except Exception as e:
        logger.error(f"Erro ao listar arquivos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{filename}")
async def download_transcribed_file(filename: str):
    """Download de arquivo transcrito"""
    try:
        file_path = Path(settings.OUTPUT_DIR) / filename
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='text/plain'
        )
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo: {e}")
        raise HTTPException(status_code=500, detail=str(e))