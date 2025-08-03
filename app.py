# app.py
import whisper
import time
import os
import threading
import logging
from datetime import datetime

# --- Configurações ---
MODEL_NAME = "medium"  # Modelo especificado no PDF
DEVICE = "cpu"         # Como é ARM sem GPU, conforme PDF
POLLING_INTERVAL = 300 # 5 minutos em segundos, conforme PDF
INPUT_GDRIVE_FOLDER = "/input"
INPUT_WEB_FOLDER = "/input_web"
OUTPUT_PARTS_FOLDER = "/output_parts"
OUTPUT_FOLDER = "/output"
LOGS_FOLDER = "/logs"

# Configuração de Logging (centralizado, conforme PDF)
log_file_path = os.path.join(LOGS_FOLDER, "app.log")
os.makedirs(LOGS_FOLDER, exist_ok=True) # Garante que a pasta de logs exista

# Configura o logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(threadName)s: %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler() # Também imprime no console do container
    ]
)
logger = logging.getLogger(__name__)
# --------------------

def load_whisper_model():
    """Carrega o modelo Whisper uma vez na inicialização."""
    logger.info(f"Carregando modelo Whisper '{MODEL_NAME}' no dispositivo '{DEVICE}'...")
    try:
        # Certifique-se de que o openai-whisper esteja instalado corretamente
        model = whisper.load_model(MODEL_NAME, device=DEVICE)
        logger.info("Modelo Whisper carregado com sucesso!")
        return model
    except Exception as e:
        logger.error(f"Falha ao carregar o modelo Whisper: {e}")
        raise # Re-levanta a exceção para parar a aplicação se o modelo não carregar

def worker_gdrive(model):
    """Worker para monitorar e processar arquivos do Google Drive."""
    logger.info(f"[WORKER-GDRIVE] Iniciado. Monitorando pasta: {INPUT_GDRIVE_FOLDER}")
    while True:
        try:
            # Lógica de processamento do worker GDrive vai aqui
            logger.info("[WORKER-GDRIVE] Verificando arquivos para processamento...")
            # TODO: Implementar lógica real de varredura e transcrição
            time.sleep(2) # Simulação de trabalho
            logger.debug("[WORKER-GDRIVE] Verificação concluída.")
        except Exception as e:
            logger.error(f"[WORKER-GDRIVE] Erro no worker: {e}")
        time.sleep(POLLING_INTERVAL) # Espera o intervalo definido

def worker_web(model):
    """Worker para monitorar e processar uploads da WebUI."""
    logger.info(f"[WORKER-WEB] Iniciado. Monitorando pasta: {INPUT_WEB_FOLDER}")
    while True:
        try:
            # Lógica de processamento do worker Web vai aqui
            logger.info("[WORKER-WEB] Verificando arquivos para processamento...")
            # TODO: Implementar lógica real de varredura e transcrição
            time.sleep(2) # Simulação de trabalho
            logger.debug("[WORKER-WEB] Verificação concluída.")
        except Exception as e:
             logger.error(f"[WORKER-WEB] Erro no worker: {e}")
        time.sleep(POLLING_INTERVAL) # Espera o intervalo definido

def main():
    """Função principal que inicia o aplicativo."""
    logger.info("Iniciando aplicação Whisper Transcription...")
    
    # 1. Carrega o modelo Whisper (uma única vez)
    try:
        model = load_whisper_model()
    except Exception as e:
        logger.critical(f"Não foi possível iniciar a aplicação devido a um erro no carregamento do modelo: {e}")
        return

    # 2. Inicia os workers em threads separadas
    logger.info("Iniciando workers em threads...")
    thread_gdrive = threading.Thread(target=worker_gdrive, args=(model,), name="Worker-GDrive", daemon=True)
    thread_web = threading.Thread(target=worker_web, args=(model,), name="Worker-Web", daemon=True)
    
    thread_gdrive.start()
    thread_web.start()
    logger.info("Workers iniciados com sucesso.")

    # 3. Mantém a aplicação principal viva
    try:
        logger.info("Aplicação principal em execução. Aguardando workers...")
        # Threads daemon encerram quando o programa principal encerra.
        # Podemos usar um loop simples para manter o programa ativo.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Recebido sinal de interrupção. Finalizando aplicação...")
    finally:
        logger.info("Aplicação encerrada.")

if __name__ == "__main__":
    main()