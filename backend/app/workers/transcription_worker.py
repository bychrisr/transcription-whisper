import os
import logging
from pathlib import Path
from celery import Celery
import whisper
from app.core.config import settings

# Configuração do Celery
celery_app = Celery('whisper_worker')
celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar modelo Whisper (uma vez)
logger.info("Carregando modelo Whisper...")
try:
    model = whisper.load_model("medium")
    logger.info("Modelo Whisper carregado com sucesso!")
except Exception as e:
    logger.error(f"Erro ao carregar modelo Whisper: {e}")
    model = None

@celery_app.task(bind=True)
def transcribe_audio_task(self, file_path: str, task_id: str):
    """Task de transcrição de áudio"""
    try:
        if model is None:
            raise Exception("Modelo Whisper não está carregado")
        
        logger.info(f"Iniciando transcrição para {file_path}")
        
        # Atualizar progresso
        self.update_state(state='PROGRESS', meta={'status': 'transcribing', 'progress': 10})
        
        # Transcrever arquivo
        result = model.transcribe(file_path, fp16=False)
        
        # Atualizar progresso
        self.update_state(state='PROGRESS', meta={'status': 'saving', 'progress': 90})
        
        # Salvar transcrição
        output_filename = Path(file_path).stem + '.txt'
        output_path = Path(settings.OUTPUT_DIR) / output_filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result["text"])
        
        # Limpar arquivo original
        try:
            os.remove(file_path)
            logger.info(f"Arquivo original removido: {file_path}")
        except Exception as e:
            logger.warning(f"Não foi possível remover arquivo original: {e}")
        
        logger.info(f"Transcrição concluída: {output_path}")
        
        return {
            'status': 'completed',
            'task_id': task_id,
            'output_file': str(output_path),
            'text_length': len(result["text"])
        }
        
    except Exception as exc:
        logger.error(f"Erro na transcrição: {exc}")
        self.update_state(
            state='FAILURE',
            meta={'status': 'error', 'error': str(exc)}
        )
        raise exc

if __name__ == '__main__':
    celery_app.start()