import os
import logging
import requests
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.token = settings.TELEGRAM_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not configured - notifications disabled")
            self.enabled = False
        else:
            self.enabled = True
            logger.info("Telegram service initialized")
    
    def send_message(self, message: str, disable_notification: bool = False) -> bool:
        """Enviar mensagem via Telegram"""
        if not self.enabled:
            return False
            
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "disable_notification": disable_notification,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Telegram message sent: {message[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def send_transcription_completed(self, filename: str, duration: Optional[str] = None) -> bool:
        """Notificação de transcrição concluída"""
        if duration:
            message = f"✅ *Transcrição Concluída*\n\n📄 Arquivo: `{filename}`\n⏱ Duração: `{duration}`"
        else:
            message = f"✅ *Transcrição Concluída*\n\n📄 Arquivo: `{filename}`"
        
        return self.send_message(message)
    
    def send_merge_completed(self, base_name: str, parts_count: int) -> bool:
        """Notificação de merge concluído"""
        message = f"🔗 *Merge Concluído*\n\n🎓 Curso/Módulo: `{base_name}`\n🔢 Partes processadas: `{parts_count}`"
        return self.send_message(message)
    
    def send_error_notification(self, error_message: str, context: str = "") -> bool:
        """Notificação de erro no sistema"""
        message = f"❌ *Erro no Sistema*\n\n⚠️ Contexto: `{context}`\n📝 Detalhe: `{error_message}`"
        return self.send_message(message, disable_notification=False)  # Sempre notificar erros
    
    def send_system_status(self, status: str, details: str = "") -> bool:
        """Notificação de status do sistema"""
        if status.lower() == "healthy":
            message = f"🟢 *Sistema Saudável*\n\n{details}" if details else "🟢 *Sistema Saudável*"
        else:
            message = f"🟡 *Status do Sistema: {status}*\n\n{details}" if details else f"🟡 *Status do Sistema: {status}*"
        
        return self.send_message(message)

# Instância singleton para uso em toda a aplicação
telegram_service = TelegramService()