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

@router.get("/merge-status/{base_name}")
async def get_merge_status(base_name: str):
    """Verificar status do merge de partes"""
    try:
        merge_service = AudioMergeService(
            settings.INPUT_DIR,
            settings.OUTPUT_PARTS_DIR,
            settings.OUTPUT_DIR
        )
        
        parts = merge_service.find_audio_parts(base_name)
        can_merge = merge_service.can_merge_parts(base_name)
        merged_file_exists = (Path(settings.OUTPUT_DIR) / f"{base_name}.txt").exists()
        
        return {
            "base_name": base_name,
            "parts_found": len(parts),
            "parts_list": [part.name for part in parts],
            "can_merge": can_merge,
            "merged_file_exists": merged_file_exists
        }
    except Exception as e:
        logger.error(f"Erro ao verificar status do merge: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/force-merge/{base_name}")
async def force_merge_parts(base_name: str):
    """Forçar merge de partes (mesmo que incompletas)"""
    try:
        merge_service = AudioMergeService(
            settings.INPUT_DIR,
            settings.OUTPUT_PARTS_DIR,
            settings.OUTPUT_DIR
        )
        
        parts = merge_service.find_audio_parts(base_name)
        if not parts:
            raise HTTPException(status_code=404, detail="Nenhuma parte encontrada")
        
        # Forçar merge ordenando as partes disponíveis
        output_file = merge_service.merge_audio_parts(base_name)
        
        if output_file:
            return {
                "status": "completed",
                "merged_file": output_file.name,
                "message": "Merge forçado concluído"
            }
        else:
            raise HTTPException(status_code=500, detail="Falha ao fazer merge forçado")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao forçar merge: {e}")
        raise HTTPException(status_code=500, detail=str(e))