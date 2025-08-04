# --- Imports e Configurações Iniciais ---
import os
import glob
import shutil
import threading
import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import json
import shutil
import psutil # Para métricas do sistema (CPU, RAM)

# Whisper e Torch
import whisper
import torch

# FastAPI
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware # Para facilitar chamadas da WebUI
from fastapi.responses import StreamingResponse

# Para parsing de formulários multipart (upload)
from python_multipart import *
import aiofiles

# Para notificações via Telegram
import requests

# --- Configuração do App ---
app = FastAPI(title="Whisper Transcription API")

# Configuração CORS para permitir que a WebUI (potencialmente em outro host/porta) acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, restrinja isso para os domínios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuração de Logs ---
# Configura o logger principal para o arquivo de log
logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s' # Adiciona threadName
)

# Logger específico para métricas
metrics_logger = logging.getLogger("metrics")
metrics_handler = logging.FileHandler('logs/metrics.log')
metrics_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
metrics_logger.addHandler(metrics_handler)
metrics_logger.setLevel(logging.INFO)

# --- Configuração de Pastas ---
INPUT_DIR = "input"
INPUT_WEB_DIR = "input_web"
OUTPUT_PARTS_DIR = "output_parts"
OUTPUT_DIR = "output"
LOGS_DIR = "logs"
WEBUI_DIR = "webui/dist" # Diretório onde os arquivos estáticos da WebUI foram construídos

# Criar diretórios se não existirem
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(INPUT_WEB_DIR, exist_ok=True)
os.makedirs(OUTPUT_PARTS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(WEBUI_DIR, exist_ok=True) # Garantir que o diretório exista

# --- Configuração do Modelo Whisper ---
# Permitir configurar via env var, padrão 'tiny' para desenvolvimento
MODEL_NAME = os.getenv("WHISPER_MODEL", "tiny")
print(f"Carregando modelo Whisper '{MODEL_NAME}'...")
model = whisper.load_model(MODEL_NAME) # Carregado uma vez na inicialização
print("Modelo Whisper carregado com sucesso.")

# --- Configuração do Telegram ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    """Envia uma mensagem via Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurados. Mensagem não enviada.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        logging.info(f"Telegram message sent: {message}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send Telegram message: {e}")

# --- Gerenciamento de Estado (state_manager) ---
# Usaremos variáveis globais protegidas por locks para simplicidade e thread-safety
from threading import Lock

# Lock para proteger o acesso ao estado compartilhado
state_lock = Lock()

# Estado dos workers
workers_status = {
    "gdrive": {"status": "running", "last_check": None},
    "web": {"status": "running", "last_check": None}
}

# Métricas de performance (simplificadas)
# Estrutura para armazenar dados brutos de métricas
performance_metrics = {
    "transcription_times": [], # {"model": str, "audio_duration_min": float, "transcription_duration_sec": float}
    "process_times": [] # {"file_identifier": str, "total_duration_sec": float}
}

# --- Funções de Processamento (Workers) ---

def get_audio_duration(file_path):
    """Estima a duração do áudio em minutos usando FFmpeg (se disponível) ou tamanho do arquivo."""
    # Esta é uma estimativa simplificada. Para precisão, use ffprobe.
    # Exemplo com ffprobe (requer instalação):
    # import subprocess
    # try:
    #     result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
    #                              "format=duration", "-of",
    #                              "default=noprint_wrappers=1:nokey=1", file_path],
    #                             capture_output=True, text=True, check=True)
    #     duration_seconds = float(result.stdout)
    #     return duration_seconds / 60.0
    # except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
    #     logging.warning(f"Could not determine duration for {file_path}. Using file size estimation.")
    #     # Fallback: Estimativa grosseira (não muito precisa)
    #     return os.path.getsize(file_path) / (1024 * 1024 * 0.5) # Assume ~0.5 MB/min (varia muito!)
    # Fallback simplificado: Retorna 15 min por padrão (seu corte padrão)
    # Você pode querer implementar a versão com ffprobe para melhor precisão.
    return 15.0 # Assumindo 15 minutos por parte como padrão

def process_audio_file(file_path, output_parts_dir, model_name):
    """Processa um único arquivo de áudio."""
    start_time = time.time()
    try:
        logging.info(f"Iniciando transcrição de: {file_path}")
        # Extrair nome base (sem extensão)
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        txt_file_path = os.path.join(output_parts_dir, f"{base_name}.txt")

        # Estimar duração do áudio (para métricas)
        audio_duration_min = get_audio_duration(file_path)

        # Registrar início da transcrição para métricas
        transcription_start_time = time.time()

        # Transcrever usando Whisper
        result = model.transcribe(file_path, verbose=False) # verbose=False para menos logs
        transcription_text = result["text"]

        # Registrar fim da transcrição e calcular duração
        transcription_end_time = time.time()
        transcription_duration_sec = transcription_end_time - transcription_start_time

        # Salvar transcrição (sem timestamps)
        with open(txt_file_path, "w", encoding='utf-8') as f:
            f.write(transcription_text)

        logging.info(f"Transcrição salva em: {txt_file_path}")

        # --- Registrar métrica de transcrição ---
        with state_lock:
            performance_metrics["transcription_times"].append({
                "model": model_name,
                "audio_duration_min": audio_duration_min,
                "transcription_duration_sec": transcription_duration_sec
            })
        metrics_logger.info(f"Métrica de Transcrição: Modelo={model_name}, DuraçãoÁudio={audio_duration_min:.2f}min, TempoTranscrição={transcription_duration_sec:.2f}s")

        return txt_file_path
    except Exception as e:
        logging.error(f"Erro ao processar {file_path}: {e}")
        return None
    finally:
        end_time = time.time()
        logging.info(f"Tempo total de processamento (thread) para {file_path}: {end_time - start_time:.2f}s")


def check_and_merge_parts(course_dir, module_dir, base_name_no_part, output_parts_dir, output_dir, initial_upload_time):
    """Verifica se todas as partes estão presentes e faz o merge."""
    merge_start_time = time.time()
    try:
        # Encontrar todas as partes correspondentes
        pattern = os.path.join(output_parts_dir, course_dir, module_dir, f"{base_name_no_part}_part*.txt")
        part_files = sorted(glob.glob(pattern), key=lambda x: int(os.path.splitext(x)[0].split('_part')[-1]))

        if not part_files:
             # Pode não haver partes ainda, ou nome base errado
             return

        # Extrair números das partes
        part_numbers = [int(os.path.splitext(f)[0].split('_part')[-1]) for f in part_files]
        expected_numbers = list(range(1, max(part_numbers) + 1))

        # Verificar se todas as partes esperadas estão presentes
        if part_numbers == expected_numbers:
            logging.info(f"Todas as partes encontradas para {base_name_no_part}. Iniciando merge...")
            merged_content = ""
            for part_file in part_files:
                 try:
                     with open(part_file, 'r', encoding='utf-8') as f:
                         merged_content += f.read() + "\n\n"
                 except Exception as e:
                     logging.error(f"Erro ao ler parte {part_file} para merge: {e}")
                     return # Abortar merge se houver erro

            # Caminho final do arquivo mergeado
            final_output_dir = os.path.join(output_dir, course_dir, module_dir)
            os.makedirs(final_output_dir, exist_ok=True)
            final_txt_path = os.path.join(final_output_dir, f"{base_name_no_part}.txt")

            try:
                with open(final_txt_path, 'w', encoding='utf-8') as f:
                    f.write(merged_content.strip()) # Remover possíveis novas linhas extras no final
                logging.info(f"Merge concluído: {final_txt_path}")

                # Calcular tempo total do processo (upload -> merge)
                if initial_upload_time:
                    process_end_time = time.time()
                    total_process_duration_sec = process_end_time - initial_upload_time
                    # --- Registrar métrica de processo completo ---
                    with state_lock:
                        performance_metrics["process_times"].append({
                            "file_identifier": f"{course_dir}/{module_dir}/{base_name_no_part}",
                            "total_duration_sec": total_process_duration_sec
                        })
                    metrics_logger.info(f"Métrica de Processo Completo: Arquivo={base_name_no_part}, TempoTotal={total_process_duration_sec:.2f}s")

                # Notificar via Telegram
                send_telegram_message(f"✅ Áudio finalizado: {final_txt_path}")

                # Limpar arquivos temporários (partes .txt e .mp3 originais)
                # Encontrar .mp3 originais
                input_pattern = os.path.join(INPUT_DIR, course_dir, module_dir, f"{base_name_no_part}_part*.mp3")
                input_web_pattern = os.path.join(INPUT_WEB_DIR, course_dir, module_dir, f"{base_name_no_part}_part*.mp3")
                original_mp3s = glob.glob(input_pattern) + glob.glob(input_web_pattern)

                for part_file in part_files:
                     try:
                         os.remove(part_file)
                         logging.info(f"Parte temporária removida: {part_file}")
                     except OSError as e:
                         logging.warning(f"Não foi possível remover parte temporária {part_file}: {e}")

                for mp3_file in original_mp3s:
                     try:
                         os.remove(mp3_file)
                         logging.info(f"Áudio original removido: {mp3_file}")
                     except OSError as e:
                         logging.warning(f"Não foi possível remover áudio original {mp3_file}: {e}")

                # Verificar e remover pastas vazias
                check_and_remove_empty_dirs(course_dir, module_dir)

            except Exception as e:
                logging.error(f"Erro ao salvar ou limpar após merge {final_txt_path}: {e}")
        else:
             missing = set(expected_numbers) - set(part_numbers)
             logging.info(f"Aguardando partes para {base_name_no_part}. Faltando: {missing}")
    finally:
        merge_end_time = time.time()
        logging.info(f"Tempo total de merge/check para {base_name_no_part}: {merge_end_time - merge_start_time:.2f}s")

def check_and_remove_empty_dirs(course_dir, module_dir):
    """Verifica e remove pastas de módulo e curso se estiverem vazias."""
    # Verificar pasta do módulo
    module_path_input = os.path.join(INPUT_DIR, course_dir, module_dir)
    module_path_input_web = os.path.join(INPUT_WEB_DIR, course_dir, module_dir)
    # module_path_output = os.path.join(OUTPUT_DIR, course_dir, module_dir) # Não precisamos verificar output aqui

    if os.path.exists(module_path_input) and not any(os.scandir(module_path_input)):
        try:
            os.rmdir(module_path_input)
            logging.info(f"Pasta de módulo vazia removida: {module_path_input}")
            send_telegram_message(f"📁 Módulo finalizado (pasta vazia): {module_path_input}")
        except OSError as e:
            logging.warning(f"Não foi possível remover pasta de módulo {module_path_input}: {e}")

    if os.path.exists(module_path_input_web) and not any(os.scandir(module_path_input_web)):
        try:
            os.rmdir(module_path_input_web)
            logging.info(f"Pasta de módulo vazia removida: {module_path_input_web}")
        except OSError as e:
            logging.warning(f"Não foi possível remover pasta de módulo {module_path_input_web}: {e}")

    # Verificar pasta do curso (após verificar módulo)
    course_path_input = os.path.join(INPUT_DIR, course_dir)
    course_path_input_web = os.path.join(INPUT_WEB_DIR, course_dir)
    # course_path_output = os.path.join(OUTPUT_DIR, course_dir) # Não precisamos verificar output aqui

    if os.path.exists(course_path_input) and not any(os.scandir(course_path_input)):
        try:
            os.rmdir(course_path_input)
            logging.info(f"Pasta de curso vazia removida: {course_path_input}")
            send_telegram_message(f"🎓 Curso finalizado (diretório vazio): {course_path_input}")
        except OSError as e:
           logging.warning(f"Não foi possível remover pasta de curso {course_path_input}: {e}")

    if os.path.exists(course_path_input_web) and not any(os.scandir(course_path_input_web)):
        try:
            os.rmdir(course_path_input_web)
            logging.info(f"Pasta de curso vazia removida: {course_path_input_web}")
        except OSError as e:
           logging.warning(f"Não foi possível remover pasta de curso {course_path_input_web}: {e}")


def worker_scan_folder(input_folder, output_parts_base_dir, priority, worker_name):
    """Worker genérico para varrer uma pasta de entrada."""
    logging.info(f"Worker para {input_folder} (nome: {worker_name}) iniciado (prioridade {priority}).")
    while True:
        try:
            with state_lock:
                 workers_status[worker_name]["last_check"] = datetime.utcnow().isoformat() + "Z"

            # Varredura da pasta de entrada
            for root, dirs, files in os.walk(input_folder):
                for file in files:
                    if file.endswith(".mp3") and "_part" in file:
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(root, input_folder)
                        # Determinar pastas de saída com base na estrutura
                        output_parts_dir_for_file = os.path.join(output_parts_base_dir, relative_path)
                        os.makedirs(output_parts_dir_for_file, exist_ok=True)

                        # Extrair nome base sem _partN
                        base_name = os.path.splitext(file)[0] # nome_part1
                        if "_part" in base_name:
                            base_name_no_part = "_".join(base_name.split("_part")[:-1]) # nome
                        else:
                            base_name_no_part = base_name

                        # Determinar curso e módulo a partir do caminho relativo
                        path_parts = relative_path.split(os.sep)
                        course_dir = path_parts[0] if len(path_parts) > 0 else ""
                        module_dir = path_parts[1] if len(path_parts) > 1 else ""

                        # Verificar se a transcrição da parte já existe
                        expected_txt_path = os.path.join(output_parts_dir_for_file, f"{base_name}.txt")
                        if not os.path.exists(expected_txt_path):
                            # Registrar tempo de upload inicial (simplificado)
                            # Na prática, você pode querer armazenar isso em um arquivo de metadados ou banco de dados
                            # Aqui, vamos usar o tempo de modificação do arquivo como proxy
                            initial_upload_time = os.path.getctime(file_path)

                            # Processar o arquivo
                            process_audio_file(file_path, output_parts_dir_for_file, MODEL_NAME) # Passa o modelo atual
                            # Após processar, verificar se pode fazer merge
                            check_and_merge_parts(course_dir, module_dir, base_name_no_part, output_parts_base_dir, OUTPUT_DIR, initial_upload_time)
                        else:
                            logging.debug(f"Transcrição já existe para {file_path}, pulando.")

        except Exception as e:
            logging.error(f"Erro no worker {worker_name} ({input_folder}): {e}")

        # Esperar antes da próxima varredura (polling controlado)
        time.sleep(300) # 5 minutos

# --- Rotas da API ---

# Endpoint para verificar status básico
@app.get("/api/status")
async def get_status():
    try:
        # Contar arquivos nas filas
        queue_web_size = sum(len(files) for _, _, files in os.walk(INPUT_WEB_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
        queue_gdrive_size = sum(len(files) for _, _, files in os.walk(INPUT_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
        # Contar transcrições finalizadas
        total_transcriptions = sum(len(files) for _, _, files in os.walk(OUTPUT_DIR) if any(f.endswith('.txt') for f in files))

        # Obter status dos workers
        with state_lock:
            worker_statuses = workers_status.copy()

        return JSONResponse(content={
            "status": "running",
            "model": MODEL_NAME,
            "queue_web_size": queue_web_size,
            "queue_gdrive_size": queue_gdrive_size,
            "total_transcriptions": total_transcriptions,
            "workers": worker_statuses,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
    except Exception as e:
        logging.error(f"Erro ao obter status: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao obter status")

# Endpoint para status detalhado (com métricas)
@app.get("/api/status/detailed")
async def get_status_detailed():
    try:
        # Contar arquivos nas filas
        queue_web_size = sum(len(files) for _, _, files in os.walk(INPUT_WEB_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
        queue_gdrive_size = sum(len(files) for _, _, files in os.walk(INPUT_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
        # Contar transcrições finalizadas
        total_transcriptions = sum(len(files) for _, _, files in os.walk(OUTPUT_DIR) if any(f.endswith('.txt') for f in files))

        # Obter status dos workers
        with state_lock:
            worker_statuses = workers_status.copy()
            # Copiar métricas para evitar modificações durante o cálculo
            metrics_copy = {
                "transcription_times": performance_metrics["transcription_times"][:],
                "process_times": performance_metrics["process_times"][:]
            }

        # Calcular métricas agregadas
        avg_transcription_speed_per_model = {}
        models_in_output = set()

        # Identificar modelos presentes nos arquivos de saída (simplificado)
        # Idealmente, isso seria armazenado com os dados de métrica
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for file in files:
                if file.endswith(".txt"):
                     # Aqui você poderia ler o arquivo e extrair o modelo usado
                     # Por simplicidade, vamos assumir que o modelo atual é o usado
                     # ou que todos os arquivos foram feitos com o modelo atual
                     models_in_output.add(MODEL_NAME)

        # Calcular médias por modelo
        model_times = defaultdict(list)
        for metric in metrics_copy["transcription_times"]:
            model = metric["model"]
            audio_duration = metric["audio_duration_min"]
            transcription_time = metric["transcription_duration_sec"]

            if audio_duration > 0: # Evitar divisão por zero
                speed_sec_per_min = transcription_time / audio_duration
                model_times[model].append(speed_sec_per_min)

        for model, speeds in model_times.items():
            if speeds:
                avg_speed = sum(speeds) / len(speeds)
                avg_transcription_speed_per_model[model] = round(avg_speed, 2) # segundos por minuto

        # Calcular média do processo inteiro
        avg_process_time = None
        if metrics_copy["process_times"]:
            total_process_times = [m["total_duration_sec"] for m in metrics_copy["process_times"]]
            avg_process_time = round(sum(total_process_times) / len(total_process_times), 2) # segundos

        return JSONResponse(content={
            "status": "running",
            "model": MODEL_NAME,
            "models_in_output": list(models_in_output), # Modelos encontrados em /output
            "queue_web_size": queue_web_size,
            "queue_gdrive_size": queue_gdrive_size,
            "total_transcriptions": total_transcriptions,
            "workers": worker_statuses,
            "metrics": {
                "avg_transcription_speed_per_model": avg_transcription_speed_per_model,
                "avg_process_time_sec": avg_process_time, # Média total do processo
                # Você pode adicionar mais métricas aqui
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
    except Exception as e:
        logging.error(f"Erro ao obter status detalhado: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao obter status detalhado")

# Endpoint para listar transcrições
@app.get("/api/transcriptions")
async def list_transcriptions():
    transcriptions = []
    try:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for file in files:
                if file.endswith(".txt"):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, OUTPUT_DIR)
                    # Tentar estimar duração (simplificado)
                    duration = None # get_audio_duration(full_path) # Pode ser pesado
                    transcriptions.append({
                        "name": file,
                        "path": relative_path, # Caminho relativo para download
                        "size": os.path.getsize(full_path),
                        "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).isoformat(),
                        "duration": duration
                    })
        return JSONResponse(content=transcriptions)
    except Exception as e:
        logging.error(f"Erro ao listar transcrições: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao listar transcrições")

# Endpoint para download de transcrição
@app.get("/api/download/{full_path:path}")
async def download_transcription(full_path: str):
    file_path = os.path.join(OUTPUT_DIR, full_path)
    # Segurança: Garantir que o caminho solicitado esteja dentro de OUTPUT_DIR
    if os.path.exists(file_path) and os.path.isfile(file_path) and os.path.commonpath([os.path.abspath(OUTPUT_DIR), os.path.abspath(file_path)]) == os.path.abspath(OUTPUT_DIR):
        return FileResponse(file_path, media_type='text/plain', filename=os.path.basename(file_path))
    else:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

# Endpoint para upload (básico)
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Salvar o arquivo na pasta input_web
        # Presume que o upload já vem com a estrutura de pastas correta
        # ou que você vai definir um padrão (ex: curso/modulo no nome)
        # Para simplificar, vamos salvar diretamente em input_web
        # Você pode querer adicionar lógica para criar pastas dinamicamente
        # Exemplo: Criar uma pasta padrão para uploads
        upload_dir = os.path.join(INPUT_WEB_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_location = os.path.join(upload_dir, file.filename)

        async with aiofiles.open(file_location, 'wb') as out_file:
            content = await file.read()  # async read
            await out_file.write(content)  # async write

        logging.info(f"Arquivo carregado: {file_location}")
        return JSONResponse(content={"message": "Arquivo carregado com sucesso", "filename": file.filename})
    except Exception as e:
        logging.error(f"Erro ao fazer upload: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao fazer upload: {str(e)}")

# Endpoint para métricas de performance específicas
@app.get("/api/metrics/performance")
async def get_performance_metrics():
    """Endpoint dedicado para fornecer dados de métricas de performance para o dashboard."""
    try:
        with state_lock:
            # Copiar métricas para evitar modificações durante o cálculo
            metrics_copy = {
                "transcription_times": performance_metrics["transcription_times"][:],
                "process_times": performance_metrics["process_times"][:]
            }

        # Preparar dados para o frontend
        # Estrutura: { "tiny": [...], "base": [...] }
        transcription_data_by_model = defaultdict(list)
        for metric in metrics_copy["transcription_times"]:
            model = metric["model"]
            # Armazenar o objeto completo ou apenas os dados necessários
            transcription_data_by_model[model].append({
                "audio_duration_min": metric["audio_duration_min"],
                "transcription_duration_sec": metric["transcription_duration_sec"],
                "speed_sec_per_min": metric["transcription_duration_sec"] / metric["audio_duration_min"] if metric["audio_duration_min"] > 0 else 0
            })

        process_times_data = metrics_copy["process_times"] # [{...}, ...]

        return JSONResponse(content={
            "transcription_data_by_model": dict(transcription_data_by_model),
            "process_times_data": process_times_data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
    except Exception as e:
        logging.error(f"Erro ao obter métricas de performance: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao obter métricas de performance")


# --- Novo Endpoint para Upload de Arquivos para o Servidor ---
# Certifique-se de que a pasta 'uploads' existe
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

@app.post("/api/upload_server_file")
async def upload_server_file(file: UploadFile = File(...)):
    """
    Endpoint para fazer upload de arquivos genéricos para a pasta 'uploads' do servidor.
    Útil para subir o template da WebUI ou outros arquivos necessários.
    """
    try:
        # Definir o caminho completo do arquivo
        file_location = os.path.join(UPLOADS_DIR, file.filename)

        # Abrir o arquivo no destino e escrever o conteúdo recebido
        # Usando aiofiles para operações assíncronas
        async with aiofiles.open(file_location, 'wb') as out_file:
            content = await file.read() # Lê o conteúdo do arquivo enviado
            await out_file.write(content) # Escreve o conteúdo no arquivo local

        logging.info(f"Arquivo '{file.filename}' carregado com sucesso para '{file_location}'")
        return JSONResponse(
            content={
                "message": f"Arquivo '{file.filename}' salvo com sucesso em '{UPLOADS_DIR}'.",
                "filename": file.filename,
                "path": file_location
            },
            status_code=201 # Created
        )
    except Exception as e:
        logging.error(f"Erro ao fazer upload do arquivo para o servidor: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao salvar o arquivo: {str(e)}"
        )
# --- Fim do Novo Endpoint ---


# --- Novo Endpoint para Server-Sent Events (SSE) ---
@app.get("/api/events")
async def sse_endpoint(request: Request):
    """
    Endpoint SSE para enviar atualizações em tempo real para o frontend.
    Envia métricas do sistema e status dos workers periodicamente.
    """
    async def event_generator():
        while True:
            # Verificar se o cliente desconectou
            if await request.is_disconnected():
                print("Cliente SSE desconectado.")
                break

            try:
                # --- Coletar dados para enviar ---
                # 1. Métricas do Sistema
                cpu_percent = psutil.cpu_percent(interval=1) # Bloqueante por 1s, mas ok para thread
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                memory_used_gb = round(memory.used / (1024**3), 2)
                memory_total_gb = round(memory.total / (1024**3), 2)

                # 2. Status dos Workers (do state_manager ou variáveis compartilhadas)
                with state_lock: # Usando o lock do state_manager
                    worker_statuses = workers_status.copy()
                    # Copiar métricas para evitar modificações durante o envio
                    metrics_copy = {
                        "transcription_times": performance_metrics["transcription_times"][-10:] if performance_metrics["transcription_times"] else [], # Últimos 10
                        "process_times": performance_metrics["process_times"][-10:] if performance_metrics["process_times"] else [],
                    }

                # 3. Status da fila (simplificado)
                queue_web_size = sum(len(files) for _, _, files in os.walk(INPUT_WEB_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
                queue_gdrive_size = sum(len(files) for _, _, files in os.walk(INPUT_DIR) if any(f.endswith('.mp3') and '_part' in f for f in files))
                total_transcriptions = sum(len(files) for _, _, files in os.walk(OUTPUT_DIR) if any(f.endswith('.txt') for f in files))

                # --- Preparar o payload do evento ---
                data_payload = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "system": {
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                        "memory_used_gb": memory_used_gb,
                        "memory_total_gb": memory_total_gb,
                    },
                    "workers": worker_statuses,
                    "queue": {
                        "web_size": queue_web_size,
                        "gdrive_size": queue_gdrive_size,
                        "total_transcriptions": total_transcriptions,
                    },
                    # Você pode adicionar mais dados aqui, como status de transcrições específicas
                    # se tiver um mecanismo para rastreá-las individualmente em andamento
                    # "active_transcriptions": [...] 
                }

                # --- Enviar o evento ---
                # Formato SSE: "data: JSON_STRING\n\n"
                yield f"data: {json.dumps(data_payload)}\n\n"

                # Aguardar antes de enviar o próximo evento
                # Use asyncio.sleep para não bloquear o loop de eventos do FastAPI
                await asyncio.sleep(2) # Envia atualização a cada 2 segundos

            except Exception as e:
                print(f"Erro no gerador de eventos SSE: {e}")
                # Em caso de erro, envia um evento de erro e encerra
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                break

    # Retornar uma StreamingResponse com o tipo de conteúdo 'text/event-stream'
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Fim do Novo Endpoint SSE ---


# --- Servir a WebUI ---
# IMPORTANTE: Esta linha deve vir DEPOIS de todas as outras rotas @app.get/@app.post/etc
# para que as rotas da API tenham prioridade sobre o fallback estático.
# Serve a WebUI a partir da raiz
app.mount("/", StaticFiles(directory=WEBUI_DIR, html=True), name="webui")

# --- Inicialização da Aplicação ---
if __name__ == "__main__":
    import uvicorn

    # Iniciar workers em threads separadas
    # Worker para GDrive (simulado ou com lógica real)
    worker_gdrive_thread = threading.Thread(target=worker_scan_folder, args=(INPUT_DIR, OUTPUT_PARTS_DIR, 70, "gdrive"), name="Worker-GDrive", daemon=True)
    worker_gdrive_thread.start()

    # Worker para WebUI
    worker_web_thread = threading.Thread(target=worker_scan_folder, args=(INPUT_WEB_DIR, OUTPUT_PARTS_DIR, 30, "web"), name="Worker-Web", daemon=True)
    worker_web_thread.start()

    # Iniciar o servidor Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
