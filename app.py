# ~/apps/whisper-transcription-n8n/app.py
"""
Sistema Monolítico de Transcrição Whisper
Integra Whisper, Workers (GDrive, Web), FastAPI, WebUI e métricas.
Baseado no commit cd41c683, com melhorias para gatilhos imediatos e corte automático.
"""

# --- Imports e Configurações Iniciais ---
import os
import glob
import shutil
import threading
import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import json
import re  # Para sanitizar nomes
import subprocess  # Para ffmpeg
import math  # Para cálculos

# Whisper e Torch
import whisper
import torch

# FastAPI
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware  # Para facilitar chamadas da WebUI

# Para parsing de formulários multipart (upload)
# from python_multipart import * # Não é necessário importar diretamente
import aiofiles

# Para notificações via Telegram
import requests

# Para métricas de sistema
import psutil

# Para manipulação de datas/horas
import asyncio

# --- Configuração do App ---
app = FastAPI(title="Whisper Transcription API")

# Configuração CORS para permitir que a WebUI (potencialmente em outro host/porta) acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, restrinja isso para os domínios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuração de Logs ---
# Configura o logger principal para o arquivo de log
logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s'  # Adiciona threadName
)

# Logger específico para métricas
metrics_logger = logging.getLogger("metrics")
if not metrics_logger.handlers:
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
WEBUI_DIR = "webui/dist"  # Diretório onde os arquivos estáticos da WebUI foram construídos
UPLOADS_DIR = "uploads"  # Pasta para uploads genéricos via WebUI

# Criar diretórios se não existirem
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(INPUT_WEB_DIR, exist_ok=True)
os.makedirs(OUTPUT_PARTS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(WEBUI_DIR, exist_ok=True)  # Garantir que o diretório exista
os.makedirs(UPLOADS_DIR, exist_ok=True)  # Garantir que o diretório exista

# --- Configuração de Modelo Whisper ---
# Caminho para um arquivo de configuração persistente
CONFIG_FILE = "config.json"

# Função para carregar a configuração
def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Validação básica
            if "model" not in config or config["model"] not in whisper.available_models():
                # Se o modelo salvo for inválido, usa o padrão
                config["model"] = os.getenv("WHISPER_MODEL", "tiny")
            return config
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        # Se o arquivo não existir ou for inválido, usa o padrão
        default_config = {"model": os.getenv("WHISPER_MODEL", "tiny")}
        save_config(default_config)  # Cria o arquivo com o padrão
        return default_config

# Função para salvar a configuração
def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logging.error(f"Erro ao salvar configuração: {e}")

# Carrega a configuração na inicialização
app_config = load_config()
MODEL_NAME = app_config.get("model", "tiny")
print(f"Carregando modelo Whisper '{MODEL_NAME}'...")
model = whisper.load_model(MODEL_NAME)  # Carregado uma vez na inicialização
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

# --- Gerenciamento de Estado (state_manager simplificado) ---
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
    "transcription_times": [],  # {"model": str, "audio_duration_min": float, "transcription_duration_sec": float}
    "process_times": []  # {"file_identifier": str, "total_duration_sec": float}
}

# --- Funções de Processamento (Workers e Helpers) ---

def get_audio_duration(file_path):
    """Estima a duração do áudio em minutos. Simplificado."""
    # Fallback simplificado: Retorna 15 min por padrão (seu corte padrão)
    # Você pode querer implementar a versão com ffprobe para melhor precisão.
    return 15.0  # Assumindo 15 minutos por parte como padrão

def split_audio_with_ffmpeg(input_file_path, output_dir, target_duration_min=15):
    """
    Corta um arquivo de áudio em partes usando ffmpeg.
    Retorna uma lista com os caminhos dos arquivos de partes criados.
    """
    try:
        base_name = os.path.splitext(os.path.basename(input_file_path))[0]
        segment_time = target_duration_min * 60
        # Usar %03d para padronizar a numeração (part001, part002, ...)
        output_pattern = os.path.join(output_dir, f"{base_name}_part%03d.mp3")

        cmd = [
            "ffmpeg", "-i", input_file_path,
            "-f", "segment",
            "-segment_time", str(segment_time),
            "-c", "copy",  # Copia streams, não re-encode (mais rápido)
            "-y",  # Sobrescrever
            output_pattern
        ]

        logging.info(f"Iniciando corte de {input_file_path} em partes de {target_duration_min} min...")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if result.returncode != 0:
            logging.error(f"Erro ao cortar áudio {input_file_path}: {result.stderr}")
            return []

        # Listar os arquivos de partes criados
        part_pattern = os.path.join(output_dir, f"{base_name}_part*.mp3")
        created_parts = sorted(glob.glob(part_pattern))

        logging.info(f"Corte concluído. Partes criadas: {[os.path.basename(p) for p in created_parts]}")
        return created_parts

    except Exception as e:
        logging.error(f"Exceção ao cortar áudio {input_file_path}: {e}")
        return []

def handle_uploaded_file(file_path):
    """
    Lida com um arquivo recém-carregado, cortando-o se necessário e iniciando o processamento.
    Esta função é chamada em uma thread separada após o upload.
    """
    try:
        logging.info(f"Iniciando processamento pós-upload para: {file_path}")
        file_name = os.path.basename(file_path)
        file_dir = os.path.dirname(file_path)

        # 1. Verificar se o arquivo já é uma parte
        if "_part" in file_name:
            logging.info(f"Arquivo {file_name} já é uma parte. Iniciando transcrição direta.")
            # Determinar pastas de saída com base na estrutura
            relative_path = os.path.relpath(file_dir, INPUT_WEB_DIR)
            output_parts_dir_for_file = os.path.join(OUTPUT_PARTS_DIR, relative_path)
            os.makedirs(output_parts_dir_for_file, exist_ok=True)

            # Extrair nome base sem _partN
            base_name = os.path.splitext(file_name)[0]
            if "_part" in base_name:
                base_name_no_part = "_".join(base_name.split("_part")[:-1])
            else:
                base_name_no_part = base_name

            # Determinar curso e módulo a partir do caminho relativo
            path_parts = relative_path.split(os.sep)
            course_dir = path_parts[0] if len(path_parts) > 0 else ""
            module_dir = path_parts[1] if len(path_parts) > 1 else ""

            # Registrar tempo de upload inicial
            initial_upload_time = os.path.getctime(file_path)

            # Processar o arquivo
            txt_file_path = process_audio_file(file_path, output_parts_dir_for_file, MODEL_NAME)
            if txt_file_path:
                # Após processar, verificar se pode fazer merge
                check_and_merge_parts(course_dir, module_dir, base_name_no_part, OUTPUT_PARTS_DIR, OUTPUT_DIR, initial_upload_time)

        else:
            # 2. Se não for uma parte, cortar o áudio
            logging.info(f"Arquivo {file_name} não é uma parte. Iniciando corte.")
            created_parts = split_audio_with_ffmpeg(file_path, file_dir, target_duration_min=15)

            if not created_parts:
                logging.error(f"Falha ao cortar o áudio {file_path}.")
                return

            logging.info(f"Áudio cortado em {len(created_parts)} partes. Iniciando transcrição para cada parte.")

            # 3. Processar cada parte criada
            for part_path in created_parts:
                part_relative_path = os.path.relpath(os.path.dirname(part_path), INPUT_WEB_DIR)
                output_parts_dir_for_part = os.path.join(OUTPUT_PARTS_DIR, part_relative_path)
                os.makedirs(output_parts_dir_for_part, exist_ok=True)

                part_name = os.path.basename(part_path)
                base_name_part = os.path.splitext(part_name)[0]
                if "_part" in base_name_part:
                    base_name_no_part = "_".join(base_name_part.split("_part")[:-1])
                else:
                    base_name_no_part = base_name_part

                path_parts = part_relative_path.split(os.sep)
                course_dir = path_parts[0] if len(path_parts) > 0 else ""
                module_dir = path_parts[1] if len(path_parts) > 1 else ""

                # Usar o tempo de criação do arquivo original para métricas
                initial_upload_time = os.path.getctime(file_path)

                # Processar o arquivo da parte
                txt_file_path = process_audio_file(part_path, output_parts_dir_for_part, MODEL_NAME)
                if txt_file_path:
                    # Tentar fazer merge imediatamente após transcrever cada parte
                    check_and_merge_parts(course_dir, module_dir, base_name_no_part, OUTPUT_PARTS_DIR, OUTPUT_DIR, initial_upload_time)

            # 4. Opcional: Apagar o arquivo original após cortar e iniciar processamento
            try:
                os.remove(file_path)
                logging.info(f"Arquivo original removido após corte: {file_path}")
            except OSError as e:
                logging.warning(f"Não foi possível remover o arquivo original {file_path}: {e}")

    except Exception as e:
        logging.error(f"Erro ao lidar com o arquivo pós-upload {file_path}: {e}", exc_info=True)


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
        result = model.transcribe(file_path, verbose=False)  # verbose=False para menos logs
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
        # Encontrar todas as partes correspondentes a este base_name_no_part
        # Exemplo: Se base_name_no_part = "aula01", busca "aula01_part*.txt"
        pattern = os.path.join(output_parts_dir, course_dir, module_dir, f"{base_name_no_part}_part*.txt")
        part_files = sorted(glob.glob(pattern), key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split('_part')[-1]))

        if not part_files:
            # Pode não haver partes ainda, ou nome base errado
            logging.debug(f"Nenhuma parte encontrada para merge de '{base_name_no_part}' usando padrão '{pattern}'.")
            return

        logging.info(f"Encontradas partes para '{base_name_no_part}': {[os.path.basename(f) for f in part_files]}")

        # Extrair números das partes encontradas
        part_numbers = [int(os.path.splitext(os.path.basename(f))[0].split('_part')[-1]) for f in part_files]
        max_part_number = max(part_numbers) if part_numbers else 0

        # Verificar se há lacunas na sequência (ex: tem part1 e part3, mas não part2)
        expected_numbers = list(range(1, max_part_number + 1))
        missing_parts = set(expected_numbers) - set(part_numbers)

        if missing_parts:
            logging.info(f"Aguardando partes para '{base_name_no_part}'. Faltando: {[f'_part{n}' for n in sorted(missing_parts)]}")
            return  # Não faz merge se faltar partes

        # Verificar se todas as partes esperadas estão presentes
        # Esta verificação é um pouco redundante com a de cima, mas reforça
        if part_numbers == expected_numbers:
            logging.info(f"Todas as partes encontradas para '{base_name_no_part}' (1 a {max_part_number}). Iniciando merge...")
            merged_content = ""
            for part_file in part_files:
                try:
                    with open(part_file, 'r', encoding='utf-8') as f:
                        merged_content += f.read() + "\n\n"
                except Exception as e:
                    logging.error(f"Erro ao ler parte {part_file} para merge: {e}")
                    return  # Abortar merge se houver erro

            # Caminho final do arquivo mergeado
            final_output_dir = os.path.join(output_dir, course_dir, module_dir)
            os.makedirs(final_output_dir, exist_ok=True)
            final_txt_path = os.path.join(final_output_dir, f"{base_name_no_part}.txt")

            try:
                with open(final_txt_path, 'w', encoding='utf-8') as f:
                    f.write(merged_content.rstrip('\n'))  # Remove possíveis novas linhas extras no final
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
            # Esta condição talvez nunca seja atingida devido à verificação de lacunas acima,
            # mas mantém como segurança.
            logging.warning(f"Sequência de partes para '{base_name_no_part}' está inconsistente. Esperadas: {expected_numbers}, Encontradas: {part_numbers}")

    except Exception as e:
        logging.error(f"Erro crítico em check_and_merge_parts para '{base_name_no_part}': {e}", exc_info=True)  # exc_info=True para stack trace
    finally:
        merge_end_time = time.time()
        logging.debug(f"Tempo total de merge/check para '{base_name_no_part}': {merge_end_time - merge_start_time:.2f}s")


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
                        base_name = os.path.splitext(file)[0]  # nome_part1
                        if "_part" in base_name:
                            base_name_no_part = "_".join(base_name.split("_part")[:-1])  # nome
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
                            process_audio_file(file_path, output_parts_dir_for_file, MODEL_NAME)  # Passa o modelo atual
                            # Após processar, verificar se pode fazer merge
                            check_and_merge_parts(course_dir, module_dir, base_name_no_part, output_parts_base_dir, OUTPUT_DIR, initial_upload_time)
                        else:
                            logging.debug(f"Transcrição já existe para {file_path}, pulando.")

        except Exception as e:
            logging.error(f"Erro no worker {worker_name} ({input_folder}): {e}")

        # Esperar antes da próxima varredura (polling controlado)
        time.sleep(300)  # 5 minutos

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

        # --- Identificar modelos disponíveis e usados ---
        # 1. Modelos disponíveis do Whisper
        try:
            available_whisper_models = whisper.available_models()
        except Exception as e:
            logging.warning(f"Não foi possível obter modelos disponíveis do Whisper: {e}")
            available_whisper_models = [MODEL_NAME]  # Fallback

        # 2. Modelos usados (simplificado - assume o modelo atual ou lê de arquivos se quiser)
        models_in_output = set()
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for file in files:
                if file.endswith(".txt"):
                    # Lógica simplificada: assume o modelo atual foi usado
                    # Para ser mais preciso, poderia ler metadados do arquivo .txt ou .meta
                    models_in_output.add(MODEL_NAME)
        # Se nenhum arquivo foi encontrado, pelo menos liste o modelo atual
        if not models_in_output:
            models_in_output.add(MODEL_NAME)
        # --- Fim da identificação de modelos ---

        # Calcular médias por modelo
        avg_transcription_speed_per_model = {}
        model_times = defaultdict(list)
        for metric in metrics_copy["transcription_times"]:
            model = metric["model"]
            audio_duration = metric["audio_duration_min"]
            transcription_time = metric["transcription_duration_sec"]

            if audio_duration > 0:  # Evitar divisão por zero
                speed_sec_per_min = transcription_time / audio_duration
                model_times[model].append(speed_sec_per_min)

        for model, speeds in model_times.items():
            if speeds:
                avg_speed = sum(speeds) / len(speeds)
                avg_transcription_speed_per_model[model] = round(avg_speed, 2)  # segundos por minuto

        # Calcular média do processo inteiro
        avg_process_time = None
        if metrics_copy["process_times"]:
            total_process_times = [m["total_duration_sec"] for m in metrics_copy["process_times"]]
            avg_process_time = round(sum(total_process_times) / len(total_process_times), 2)  # segundos

        return JSONResponse(content={
            "status": "running",
            "model": MODEL_NAME,
            "models_in_output": list(models_in_output),  # Modelos encontrados em /output ou disponíveis
            "queue_web_size": queue_web_size,
            "queue_gdrive_size": queue_gdrive_size,
            "total_transcriptions": total_transcriptions,
            "workers": worker_statuses,
            "metrics": {
                "avg_transcription_speed_per_model": avg_transcription_speed_per_model,
                "avg_process_time_sec": avg_process_time,  # Média total do processo
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
                    duration = None  # get_audio_duration(full_path) # Pode ser pesado
                    transcriptions.append({
                        "name": file,
                        "path": relative_path,  # Caminho relativo para download
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

# Endpoint para upload (básico) - AGORA COM GATILHO IMEDIATO
@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Salvar o arquivo na pasta input_web/uploads
        upload_dir = os.path.join(INPUT_WEB_DIR, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_location = os.path.join(upload_dir, file.filename)

        async with aiofiles.open(file_location, 'wb') as out_file:
            content = await file.read()  # async read
            await out_file.write(content)  # async write

        logging.info(f"Arquivo carregado: {file_location}")

        # --- NOVIDADE: Gatilho imediato ---
        # Chama a função para lidar com o arquivo recém-carregado em uma thread
        processing_thread = threading.Thread(target=handle_uploaded_file, args=(file_location,), daemon=True)
        processing_thread.start()
        # --- FIM DA NOVIDADE ---

        return JSONResponse(content={"message": "Arquivo carregado com sucesso", "filename": file.filename})
    except Exception as e:
        logging.error(f"Erro ao fazer upload: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao fazer upload: {str(e)}")

# Endpoint para métricas de performance específicas
@app.get("/api/metrics/performance")
async def get_performance_metrics_endpoint():
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
        process_times_data = metrics_copy["process_times"]  # [{...}, ...]
        return JSONResponse(content={
            "transcription_data_by_model": dict(transcription_data_by_model),
            "process_times_data": process_times_data,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })
    except Exception as e:
        logging.error(f"Erro ao obter métricas de performance: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao obter métricas de performance")


# --- Novos Endpoints para Funcionalidades Adicionais ---

# --- 1. Seleção de Modelo ---
@app.get("/api/models")
async def list_models():
    """Lista os modelos Whisper disponíveis."""
    try:
        # whisper.available_models() pode demorar um pouco, mas é uma operação válida
        available_models = whisper.available_models()
        # Certifique-se de que o modelo atual esteja na lista
        current_model = MODEL_NAME
        return JSONResponse(content={
            "available_models": available_models,
            "current_model": current_model
        })
    except Exception as e:
        logging.error(f"Erro ao listar modelos: {e}")
        raise HTTPException(status_code=500, detail="Erro ao listar modelos")

@app.post("/api/config/model")
async def set_model(model_data: dict): # Ou crie um Pydantic model para validação
    """Define o modelo Whisper a ser usado. Requer reinicialização do container."""
    try:
        new_model_name = model_data.get("model")
        if not new_model_name:
            raise HTTPException(status_code=400, detail="Nome do modelo não fornecido.")

        # Validar se o modelo é suportado
        available_models = whisper.available_models()
        if new_model_name not in available_models:
            raise HTTPException(status_code=400, detail=f"Modelo '{new_model_name}' não é suportado. Modelos disponíveis: {available_models}")

        # Salvar a nova configuração
        save_config({"model": new_model_name})

        # Logar a mudança
        logging.info(f"Modelo configurado para '{new_model_name}'. Reinicie o container para aplicar as mudanças.")

        return JSONResponse(
            content={
                "message": f"Modelo definido para '{new_model_name}'. Reinicie o container para aplicar as mudanças.",
                "requires_restart": True
            },
            status_code=200
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro ao definir modelo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao definir modelo: {str(e)}")

# --- 2. Upload Estruturado (Curso/Módulo) - COM GATILHO IMEDIATO ---
@app.get("/api/courses")
async def list_courses():
    """Lista os cursos (pastas) em /input_web/."""
    try:
        courses = []
        if os.path.exists(INPUT_WEB_DIR):
            for item in os.listdir(INPUT_WEB_DIR):
                item_path = os.path.join(INPUT_WEB_DIR, item)
                # Listar apenas diretórios
                if os.path.isdir(item_path):
                    courses.append(item)
        # Ordenar alfabeticamente pode ser útil
        courses.sort()
        return JSONResponse(content=courses)
    except Exception as e:
        logging.error(f"Erro ao listar cursos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao listar cursos: {str(e)}")

@app.get("/api/courses/{course_name}/modules")
async def list_modules(course_name: str):
    """Lista os módulos (pastas) em /input_web/{course_name}/."""
    try:
        # Validar course_name para segurança (evitar path traversal)
        # Usar uma expressão regular simples para permitir letras, números, espaços, underscores e hífens
        if not re.match(r'^[\w\-\s]+$', course_name):
            raise HTTPException(status_code=400, detail="Nome do curso inválido.")

        safe_course_name = course_name.strip()  # Remove espaços extras
        # Substituir espaços por underscores para compatibilidade de sistema de arquivos (opcional)
        # safe_course_name = safe_course_name.replace(' ', '_')
        course_path = os.path.join(INPUT_WEB_DIR, safe_course_name)

        if not os.path.exists(course_path) or not os.path.isdir(course_path):
            # Se o curso não existir, retorna lista vazia em vez de 404
            return JSONResponse(content=[])

        modules = []
        for item in os.listdir(course_path):
            item_path = os.path.join(course_path, item)
            if os.path.isdir(item_path):
                modules.append(item)
        modules.sort()
        return JSONResponse(content=modules)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro ao listar módulos para {course_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao listar módulos: {str(e)}")


@app.post("/api/upload_structured")
async def upload_structured_file(
    file: UploadFile = File(...),
    course: str = Form(...),  # Recebe 'course' do formulário
    module: str = Form(...)   # Recebe 'module' do formulário
):
    """Endpoint para upload estruturado de arquivos. COM GATILHO IMEDIATO."""
    try:
        # Validar nomes (opcional, mas recomendado)
        if not re.match(r'^[\w\-\s]+$', course):
            raise HTTPException(status_code=400, detail="Nome do curso inválido.")
        if not re.match(r'^[\w\-\s]+$', module):
            raise HTTPException(status_code=400, detail="Nome do módulo inválido.")

        safe_course = course.strip()
        safe_module = module.strip()
        # Substituir espaços por underscores (opcional)
        # safe_course = safe_course.replace(' ', '_')
        # safe_module = safe_module.replace(' ', '_')

        # Definir o caminho completo de destino
        target_dir = os.path.join(INPUT_WEB_DIR, safe_course, safe_module)
        os.makedirs(target_dir, exist_ok=True)  # Cria pastas se não existirem
        file_location = os.path.join(target_dir, file.filename)

        # Salvar o arquivo
        async with aiofiles.open(file_location, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        logging.info(f"Arquivo estruturado carregado: {file_location}")

        # --- NOVIDADE: Gatilho imediato para upload estruturado ---
        processing_thread = threading.Thread(target=handle_uploaded_file, args=(file_location,), daemon=True)
        processing_thread.start()
        # --- FIM DA NOVIDADE ---

        return JSONResponse(
            content={
                "message": f"Arquivo '{file.filename}' carregado com sucesso para '{safe_course}/{safe_module}'. O processamento começará em breve.",
                "filename": file.filename,
                "course": safe_course,
                "module": safe_module,
                "path": file_location  # Caminho relativo ou absoluto, conforme necessidade
            },
            status_code=201  # Created
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Erro ao fazer upload estruturado: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao fazer upload estruturado: {str(e)}")

# --- 3. Upload de Arquivo Genérico para o Servidor ---
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
            content = await file.read()  # Lê o conteúdo do arquivo enviado
            await out_file.write(content)  # Escreve o conteúdo no arquivo local

        logging.info(f"Arquivo '{file.filename}' carregado com sucesso para '{file_location}'")
        return JSONResponse(
            content={
                "message": f"Arquivo '{file.filename}' salvo com sucesso em '{UPLOADS_DIR}'.",
                "filename": file.filename,
                "path": file_location
            },
            status_code=201  # Created
        )
    except Exception as e:
        logging.error(f"Erro ao fazer upload do arquivo para o servidor: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno ao salvar o arquivo: {str(e)}"
        )

# --- 4. Server-Sent Events (SSE) ---
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
                cpu_percent = psutil.cpu_percent(interval=1)  # Bloqueante por 1s, mas ok para thread
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                memory_used_gb = round(memory.used / (1024**3), 2)
                memory_total_gb = round(memory.total / (1024**3), 2)

                # 2. Status dos Workers (do state_manager ou variáveis compartilhadas)
                with state_lock:  # Usando o lock do state_manager
                    worker_statuses = workers_status.copy()
                    # Copiar métricas para evitar modificações durante o envio
                    metrics_copy = {
                        "transcription_times": performance_metrics["transcription_times"][-10:] if performance_metrics["transcription_times"] else [],  # Últimos 10
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
                yield f" {json.dumps(data_payload)}\n\n"

                # Aguardar antes de enviar o próximo evento
                # Use asyncio.sleep para não bloquear o loop de eventos do FastAPI
                await asyncio.sleep(2)  # Envia atualização a cada 2 segundos

            except Exception as e:
                print(f"Erro no gerador de eventos SSE: {e}")
                # Em caso de erro, envia um evento de erro e encerra
                yield f"event: error\n {json.dumps({'error': str(e)})}\n\n"
                break

    # Retornar uma StreamingResponse com o tipo de conteúdo 'text/event-stream'
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Servir a WebUI ---
# IMPORTANTE: Esta linha deve vir DEPOIS de todas as outras rotas @app.get/@app.post/etc
# para que as rotas da API tenham prioridade sobre o fallback estático.
# Serve a WebUI a partir da raiz
app.mount("/", StaticFiles(directory=WEBUI_DIR, html=True), name="webui")

# --- Inicialização da Aplicação ---
if __name__ == "__main__":
    import uvicorn

    # Iniciar workers em threads separadas
    # Worker para GDrive (simulado ou com lógica real - mantém polling)
    worker_gdrive_thread = threading.Thread(target=worker_scan_folder, args=(INPUT_DIR, OUTPUT_PARTS_DIR, 70, "gdrive"), name="Worker-GDrive", daemon=True)
    worker_gdrive_thread.start()

    # Worker para WebUI (mantém polling como fallback, mas uploads são processados imediatamente)
    worker_web_thread = threading.Thread(target=worker_scan_folder, args=(INPUT_WEB_DIR, OUTPUT_PARTS_DIR, 30, "web"), name="Worker-Web", daemon=True)
    worker_web_thread.start()

    # Iniciar o servidor Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
