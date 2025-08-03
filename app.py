# ~/apps/whisper-transcription-n8n/app.py
import whisper
import time
import os
import threading
import logging
import re # Para ordenar os arquivos por número da parte

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
os.makedirs(OUTPUT_PARTS_FOLDER, exist_ok=True) # Garante que a pasta de saída de partes exista

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

def get_sorted_part_files(directory, base_filename):
    """
    Encontra todos os arquivos _partN.mp3 para um base_filename em um diretório
    e os retorna ordenados pelo número da parte.
    Exemplo: Para 'aula01', encontra 'aula01_part1.mp3', 'aula01_part2.mp3'...
    """
    part_files = []
    pattern = re.compile(rf"{re.escape(base_filename)}_part(\d+)\.mp3$")
    if os.path.exists(directory):
        for filename in os.listdir(directory):
            match = pattern.match(filename)
            if match:
                part_num = int(match.group(1))
                part_files.append((part_num, filename))
        # Ordena pela parte numerica
        part_files.sort(key=lambda x: x[0])
    # Retorna apenas os nomes dos arquivos, na ordem correta
    return [f for _, f in part_files]

def transcribe_part(model, mp3_file_path, output_txt_path):
    """
    Transcreve um único arquivo .mp3 usando o modelo Whisper
    e salva o resultado em um arquivo .txt.
    """
    try:
        logger.info(f"[TRANSCRIBE] Iniciando transcrição de: {mp3_file_path}")
        
        # 1. Transcrever o áudio
        # O PDF pede transcrição "limpa" (sem timestamps)
        # `verbose=False` desativa o log do progresso do Whisper
        # `fp16=False` força o uso de precisão 32-bit float (mais compatível com CPU)
        result = model.transcribe(mp3_file_path, verbose=False, fp16=False, language="pt") # Assumindo idioma português. Pode ser dinâmico.
        
        # 2. Extrair o texto da transcrição
        transcription_text = result["text"]
        
        # 3. Salvar o texto em um arquivo .txt
        with open(output_txt_path, 'w', encoding='utf-8') as f:
            f.write(transcription_text)
        
        logger.info(f"[TRANSCRIBE] Transcrição salva em: {output_txt_path}")
        return True
    except Exception as e:
        logger.error(f"[TRANSCRIBE] Erro ao transcrever {mp3_file_path}: {e}", exc_info=True)
        return False

def worker_gdrive(model):
    """Worker para monitorar e processar arquivos do Google Drive."""
    logger.info(f"[WORKER-GDRIVE] Iniciado. Monitorando pasta: {INPUT_GDRIVE_FOLDER}")
    while True:
        try:
            # Lógica de processamento do worker GDrive vai aqui
            logger.info("[WORKER-GDRIVE] Verificando arquivos para processamento...")
            # TODO: Implementar lógica real de varredura e transcrição
            # Esta é a próxima etapa após worker_web funcionar completamente
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
            logger.info("[WORKER-WEB] Verificando arquivos para processamento...")
            
            # 1. Varre a pasta INPUT_WEB_FOLDER
            if os.path.exists(INPUT_WEB_FOLDER):
                for item in os.listdir(INPUT_WEB_FOLDER):
                    item_path = os.path.join(INPUT_WEB_FOLDER, item)
                    
                    # 2. Verifica se é um diretório (representando um "curso" ou "upload")
                    if os.path.isdir(item_path):
                        logger.debug(f"[WORKER-WEB] Encontrado diretório: {item}")
                        course_folder = item
                        course_path = item_path
                        
                        # Define o caminho de saída para este curso
                        course_output_parts_path = os.path.join(OUTPUT_PARTS_FOLDER, course_folder)
                        os.makedirs(course_output_parts_path, exist_ok=True)
                        
                        # 3. Varre os subdiretórios (módulos)
                        for module_item in os.listdir(course_path):
                            module_path = os.path.join(course_path, module_item)
                            
                            # 4. Verifica se é um diretório (representando um "módulo")
                            if os.path.isdir(module_path):
                                logger.debug(f"[WORKER-WEB] Encontrado módulo: {module_item}")
                                
                                # Define o caminho de saída para este módulo
                                module_output_parts_path = os.path.join(course_output_parts_path, module_item)
                                os.makedirs(module_output_parts_path, exist_ok=True)
                                
                                # 5. Varre os arquivos dentro do módulo
                                for audio_file in os.listdir(module_path):
                                    # 6. Verifica se é um arquivo _part1.mp3 (começa o processo)
                                    if audio_file.endswith("_part1.mp3"):
                                        # Extrai o nome base (ex: 'aula01' de 'aula01_part1.mp3')
                                        base_name = audio_file.rsplit("_part1", 1)[0]
                                        logger.info(f"[WORKER-WEB] Encontrado início de áudio: {base_name}")
                                        
                                        # 7. Encontra todas