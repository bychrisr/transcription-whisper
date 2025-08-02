import os
import shutil
from pathlib import Path
from typing import List
import logging
from fastapi import UploadFile
from app.core.config import settings

logger = logging.getLogger(__name__)

class FileService:
    def __init__(self):
        # Criar diretórios se não existirem
        Path(settings.INPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.INPUT_WEB_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.OUTPUT_PARTS_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.LOGS_DIR).mkdir(parents=True, exist_ok=True)
    
    async def save_upload_file(self, file: UploadFile) -> Path:
        """Salvar arquivo uploadado"""
        file_path = Path(settings.INPUT_WEB_DIR) / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        logger.info(f"Arquivo salvo: {file_path}")
        return file_path
    
    def list_pending_files(self, directory: str = "input_web") -> List[Path]:
        """Listar arquivos pendentes para processamento"""
        if directory == "input_web":
            search_dir = Path(settings.INPUT_WEB_DIR)
        else:
            search_dir = Path(settings.INPUT_DIR)
        
        return [f for f in search_dir.iterdir() 
                if f.is_file() and f.suffix.lower() in ['.mp3', '.wav', '.m4a', '.flac']]
    
    def move_to_processed(self, file_path: Path) -> Path:
        """Mover arquivo processado para diretório de output_parts"""
        filename = file_path.name
        destination = Path(settings.OUTPUT_PARTS_DIR) / filename.replace(file_path.suffix, '.txt')
        return destination
    
    def list_transcriptions(self) -> List[dict]:
        """Listar transcrições disponíveis para download"""
        transcriptions = []
        output_dir = Path(settings.OUTPUT_DIR)
        
        if output_dir.exists():
            for file_path in output_dir.glob("*.txt"):
                stat = file_path.stat()
                transcriptions.append({
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime
                })
        
        return transcriptions