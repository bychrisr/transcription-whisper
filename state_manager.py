# ~/apps/whisper-transcription-n8n/state_manager.py
"""
Módulo para gerenciar o estado em tempo real do sistema de transcrição.
Para a arquitetura monolítica com threads, um estado em memória é suficiente.
"""

import threading
import time
from typing import Dict, List, Any

class TranscriptionSystemState:
    """
    Classe para armazenar e gerenciar o estado do sistema de transcrição.
    """
    def __init__(self):
        self.lock = threading.Lock() # Para garantir acesso thread-safe
        
        # Estado dos workers
        self.worker_gdrive_status = {
            "status": "idle", # idle, processing, waiting
            "current_item": None, # Nome do item atualmente sendo processado
            "queue_size": 0, # Número estimado de itens na fila
            "last_update": time.time()
        }
        self.worker_web_status = {
            "status": "idle",
            "current_item": None,
            "queue_size": 0,
            "last_update": time.time()
        }
        
        # Métricas gerais
        self.metrics = {
            "total_files_processed": 0,
            "total_courses_completed": 0,
            # Outras métricas podem ser adicionadas aqui
        }
        
        # Fila de eventos (opcional, para notificações recentes)
        self.event_queue: List[Dict[str, Any]] = []

    def update_worker_status(self, worker_name: str, status: str, current_item: str = None, queue_size: int = None):
        """Atualiza o status de um worker."""
        with self.lock:
            if worker_name in ["worker_gdrive", "Worker-GDrive"]:
                target = self.worker_gdrive_status
            elif worker_name in ["worker_web", "Worker-Web"]:
                target = self.worker_web_status
            else:
                return # Worker desconhecido

            target["status"] = status
            if current_item is not None:
                target["current_item"] = current_item
            if queue_size is not None:
                target["queue_size"] = queue_size
            target["last_update"] = time.time()

    def increment_metric(self, metric_name: str, value: int = 1):
        """Incrementa uma métrica."""
        with self.lock:
            if metric_name in self.metrics:
                self.metrics[metric_name] += value
            else:
                self.metrics[metric_name] = value

    def add_event(self, event_type: str, message: str):
        """Adiciona um evento à fila de eventos."""
        with self.lock:
             self.event_queue.append({
                 "timestamp": time.time(),
                 "type": event_type,
                 "message": message
             })
             # Mantém apenas os últimos 100 eventos para evitar crescimento infinito
             if len(self.event_queue) > 100:
                 self.event_queue = self.event_queue[-100:]

    def get_state(self) -> Dict[str, Any]:
        """Retorna uma cópia do estado atual."""
        with self.lock:
            # Retorna uma cópia para evitar modificações externas acidentais
            return {
                "worker_gdrive": self.worker_gdrive_status.copy(),
                "worker_web": self.worker_web_status.copy(),
                "metrics": self.metrics.copy(),
                # Pode-se retornar uma cópia dos últimos N eventos se necessário
                # "recent_events": self.event_queue[-10:] # Por exemplo, últimos 10
            }

# Instância global do gerenciador de estado
# Em um sistema monolítico, isso é aceitável.
global_state_manager = TranscriptionSystemState()
