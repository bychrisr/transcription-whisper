# ~/apps/whisper-transcription-n8n/app.py
import whisper
import time
import os
import threading
import logging
import re # Para ordenar os arquivos por número da parte
import requests # Para notificações Telegram (manter import para futuro)
import shutil # Para salvar o arquivo uploadado
from typing import List, Dict # Para tipagem dos retornos da API
# --- Importações do FastAPI ---
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
# -----------------------------

# --- Importação do State Manager ---
from state_manager import global_state_manager # <<< Adicione esta linha
# ----------------------------------

# --- Configurações ---
MODEL_NAME = "tiny"  # Modelo especificado no PDF (ajustado para tiny para desenvolvimento)
DEVICE = "cpu"         # Como é ARM sem GPU, conforme PDF
POLLING_INTERVAL = 300 # 5 minutos em segundos, conforme PDF
INPUT_GDRIVE_FOLDER = "/input"
INPUT_WEB_FOLDER = "/input_web"
OUTPUT_PARTS_FOLDER = "/output_parts"
OUTPUT_FOLDER = "/output" # Pasta raiz para transcrições finalizadas
LOGS_FOLDER = "/logs"
# --- ATUALIZAÇÃO: Caminho para os arquivos estáticos da WebUI ---
# Este é o caminho DENTRO DO CONTAINER onde os arquivos da WebUI compilada estarão
WEBUI_STATIC_FOLDER = "/app/webui/dist" # <<< Atualizado para apontar para 'dist'
# --------------------

# --- Credenciais do Telegram (carregadas do .env) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# --------------------

# --- Configuração de Logging (centralizado, conforme PDF) ---
log_file_path = os.path.join(LOGS_FOLDER, "app.log")
os.makedirs(LOGS_FOLDER, exist_ok=True) # Garante que a pasta de logs exista
os.makedirs(OUTPUT_PARTS_FOLDER, exist_ok=True) # Garante que a pasta de saída de partes exista
os.makedirs(OUTPUT_FOLDER, exist_ok=True) # Garante que a pasta de saída final exista
os.makedirs(INPUT_WEB_FOLDER, exist_ok=True) # Garante que a pasta de input_web exista

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

# --- Instância do FastAPI ---
app = FastAPI(title="Whisper Transcription API", description="API para transcrição de áudios")
# ----------------------------

# --- Servir Arquivos Estáticos da WebUI ---
# Verifica se a pasta de arquivos estáticos existe antes de tentar servir
if os.path.isdir(WEBUI_STATIC_FOLDER):
    logger.info(f"[WEBUI] Servindo arquivos estáticos da WebUI de: {WEBUI_STATIC_FOLDER}")
    
    # Serve os arquivos estáticos (JS, CSS, imagens) de sub-rotas como /assets
    # Verifica se a subpasta 'assets' existe antes de montar
    assets_path = os.path.join(WEBUI_STATIC_FOLDER, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
        logger.info(f"[WEBUI] Pasta 'assets' montada em /assets")
    else:
         logger.warning(f"[WEBUI] Pasta 'assets' não encontrada em {assets_path}. Arquivos CSS/JS podem não carregar.")

    # Serve o index.html e outros HTMLs da raiz da pasta static
    @app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    async def read_ui_index():
        index_file_path = os.path.join(WEBUI_STATIC_FOLDER, "index.html")
        if os.path.exists(index_file_path):
            with open(index_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content)
        else:
            logger.warning(f"[WEBUI] Arquivo index.html não encontrado em {index_file_path}")
            return HTMLResponse(content="<h1>WebUI não encontrada</h1><p>index.html não encontrado.</p>", status_code=404)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def read_root():
        index_file_path = os.path.join(WEBUI_STATIC_FOLDER, "index.html")
        if os.path.exists(index_file_path):
            with open(index_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content)
        else:
            return HTMLResponse(content="<h1>API Whisper Transcription</h1><p>Acesse <a href='/ui'>/ui</a> para a interface web.</p><p>Acesse <a href='/docs'>/docs</a> para a documentação da API.</p>")

else:
    logger.warning(f"[WEBUI] Pasta de arquivos estáticos '{WEBUI_STATIC_FOLDER}' não encontrada. WebUI não será servida.")
    @app.get("/", include_in_schema=False)
    async def read_root_no_ui():
        return {"message": "API Whisper Transcription está rodando. WebUI não configurada/disponível."}

# ---------------------------------------------

# --- Modelos Pydantic para retornos da API ---
from pydantic import BaseModel
from typing import List, Optional

class TranscriptionFile(BaseModel):
    name: str
    path: str

class TranscriptionModule(BaseModel):
    name: str
    files: List[TranscriptionFile]

class TranscriptionCourse(BaseModel):
    name: str
    modules: List[TranscriptionModule]

# Modelo para o status detalhado
class WorkerStatus(BaseModel):
    status: str
    current_item: Optional[str] # <<< Usar Optional[str] ao invés de str | None
    queue_size: int
    last_update: float

class SystemMetrics(BaseModel):
    total_files_processed: int
    total_courses_completed: int

class DetailedSystemStatus(BaseModel):
    worker_gdrive: WorkerStatus
    worker_web: WorkerStatus
    metrics: SystemMetrics
# ---------------------------------------------

# --- Rotas da API (FastAPI Endpoints) ---
@app.get("/api/status", summary="Status do Sistema", description="Retorna o status básico do sistema.")
async def get_status():
    """
    Endpoint para verificar se a API está respondendo.
    """
    return {
        "status": "online",
        "message": "Sistema de transcrição Whisper está em execução.",
        "model": MODEL_NAME,
        "device": DEVICE
    }

@app.get("/api/status/detailed", response_model=DetailedSystemStatus, summary="Status Detalhado do Sistema", description="Retorna informações detalhadas sobre o estado dos workers e métricas.")
async def get_detailed_status():
    """
    Endpoint para obter o status detalhado do sistema.
    """
    state_data = global_state_manager.get_state()
    # Pydantic irá validar e serializar os dados automaticamente
    return DetailedSystemStatus(
        worker_gdrive=WorkerStatus(**state_data["worker_gdrive"]),
        worker_web=WorkerStatus(**state_data["worker_web"]),
        metrics=SystemMetrics(**state_data["metrics"])
    )

@app.post("/api/upload", summary="Upload de Arquivo", description="Faz upload de um arquivo de áudio para ser processado.")
async def upload_file(
    file: UploadFile = File(..., description="O arquivo de áudio a ser enviado (ex: .mp3, .wav)."),
    course_name: str = Form(..., description="Nome do curso (pasta de destino)."),
    module_name: str = Form(..., description="Nome do módulo (subpasta de destino).")
):
    """
    Endpoint para upload de arquivos de áudio.
    Salva o arquivo em /input_web/{course_name}/{module_name}/.
    """
    try:
        # 1. Validar o nome do arquivo (básico)
        if not file.filename:
            logger.warning("Upload falhou: Nome de arquivo vazio.")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de arquivo inválido.")

        # 2. Validar tipos de conteúdo suportados (opcional, mas recomendado)
        # Exemplo: Permitir apenas áudio/mp3 e áudio/wav
        # if file.content_type not in ["audio/mpeg", "audio/wav", "audio/mp3"]:
        #     logger.warning(f"Upload falhou: Tipo de conteúdo não suportado {file.content_type} para {file.filename}")
        #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Tipo de arquivo não suportado: {file.content_type}. Apenas MP3/WAV são aceitos.")

        # 3. Criar o caminho completo da pasta de destino
        course_path = os.path.join(INPUT_WEB_FOLDER, course_name)
        module_path = os.path.join(course_path, module_name)
        os.makedirs(module_path, exist_ok=True) # Cria pastas se não existirem

        # 4. Definir o caminho completo do arquivo de destino
        file_path = os.path.join(module_path, file.filename)

        # 5. Salvar o arquivo (usando shutil.copyfileobj para eficiência com arquivos grandes)
        logger.info(f"[UPLOAD] Iniciando upload de '{file.filename}' para '{file_path}'...")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"[UPLOAD] Arquivo '{file.filename}' salvo com sucesso em '{file_path}'.")

        # 6. Retornar resposta de sucesso
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "message": "Arquivo enviado com sucesso.",
                "filename": file.filename,
                "course": course_name,
                "module": module_name,
                "saved_path": file_path
            }
        )

    except HTTPException:
        # Re-levanta exceções HTTP já tratadas
        raise
    except Exception as e:
        logger.error(f"[UPLOAD] Erro durante o upload do arquivo '{file.filename if 'file' in locals() else 'desconhecido'}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro interno ao processar o upload.")

@app.get("/api/transcriptions", response_model=List[TranscriptionCourse], summary="Lista Transcrições", description="Lista todos os cursos, módulos e arquivos de transcrição disponíveis para download.")
async def list_transcriptions():
    """
    Endpoint para listar as transcrições disponíveis.
    Retorna uma estrutura JSON representando a hierarquia de cursos, módulos e arquivos.
    """
    try:
        courses_list = []
        if not os.path.exists(OUTPUT_FOLDER):
             logger.warning(f"[API] Pasta de saída '{OUTPUT_FOLDER}' não encontrada.")
             return courses_list # Retorna lista vazia se a pasta não existir

        # 1. Iterar por cada curso (pasta dentro de /output)
        for course_name in os.listdir(OUTPUT_FOLDER):
            course_path = os.path.join(OUTPUT_FOLDER, course_name)
            if os.path.isdir(course_path):
                course_data = TranscriptionCourse(name=course_name, modules=[])
                
                # 2. Iterar por cada módulo (subpasta do curso)
                for module_name in os.listdir(course_path):
                    module_path = os.path.join(course_path, module_name)
                    if os.path.isdir(module_path):
                        module_data = TranscriptionModule(name=module_name, files=[])
                        
                        # 3. Iterar por cada arquivo .txt no módulo
                        for filename in os.listdir(module_path):
                            if filename.endswith(".txt"):
                                file_path = os.path.join(module_path, filename)
                                # Armazena o caminho relativo para o download
                                relative_path = os.path.relpath(file_path, OUTPUT_FOLDER)
                                file_data = TranscriptionFile(name=filename, path=relative_path)
                                module_data.files.append(file_data)
                        
                        course_data.modules.append(module_data)
                
                courses_list.append(course_data)
        
        logger.info(f"[API] Listagem de transcrições retornada com {len(courses_list)} cursos encontrados.")
        return courses_list

    except Exception as e:
        logger.error(f"[API] Erro ao listar transcrições: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao listar transcrições.")

@app.get("/api/download/{full_path:path}", summary="Download de Transcrição", description="Faz o download de um arquivo de transcrição específico.")
async def download_transcription(full_path: str):
    """
    Endpoint para download de um arquivo de transcrição.
    O 'full_path' é o caminho relativo do arquivo dentro de /output (ex: 'CursoTeste/Modulo1/aula01.txt').
    """
    try:
        # 1. Construir o caminho completo do arquivo solicitado
        file_path = os.path.join(OUTPUT_FOLDER, full_path)
        
        # 2. Validar se o caminho está dentro de OUTPUT_FOLDER (segurança básica)
        # Impede acessos como ../../../etc/passwd
        if not os.path.commonpath([OUTPUT_FOLDER, file_path]) == OUTPUT_FOLDER:
             logger.warning(f"[API] Tentativa de acesso a caminho inválido: {file_path}")
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caminho de arquivo inválido.")
        
        # 3. Verificar se o arquivo existe e é um arquivo regular
        if not os.path.isfile(file_path):
            logger.warning(f"[API] Arquivo não encontrado para download: {file_path}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo não encontrado.")

        # 4. Verificar se é um arquivo .txt (segurança adicional)
        if not file_path.endswith(".txt"):
             logger.warning(f"[API] Tentativa de download de arquivo não permitido: {file_path}")
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Somente arquivos .txt podem ser baixados.")

        # 5. Determinar o nome do arquivo para o download
        filename = os.path.basename(file_path)

        # 6. Retornar o arquivo como resposta de download
        logger.info(f"[API] Iniciando download de '{file_path}'...")
        return FileResponse(path=file_path, filename=filename, media_type='text/plain')

    except HTTPException:
        # Re-levanta exceções HTTP já tratadas
        raise
    except Exception as e:
        logger.error(f"[API] Erro ao fazer download do arquivo '{full_path}': {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro interno ao processar o download.")

# TODO: Adicionar mais endpoints conforme necessário.
# ----------------------------

# --- Funções do Worker ---
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
    Retorna uma lista ordenada de nomes de arquivos (ex: ['aula01_part1.mp3', 'aula01_part2.mp3'])
    """
    part_files = []
    # Pattern para encontrar _part seguido de números e terminando em .mp3
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

def get_sorted_transcribed_part_files(directory, base_filename):
    """
    Encontra todos os arquivos _partN.txt para um base_filename em um diretório
    e os retorna ordenados pelo número da parte.
    Exemplo: Para 'aula01', encontra 'aula01_part1.txt', 'aula01_part2.txt'...
    Retorna uma lista ordenada de nomes de arquivos (ex: ['aula01_part1.txt', 'aula01_part2.txt'])
    """
    part_files = []
    # Pattern para encontrar _part seguido de números e terminando em .txt
    pattern = re.compile(rf"{re.escape(base_filename)}_part(\d+)\.txt$")
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

def are_all_parts_present(sorted_mp3_parts, sorted_txt_parts):
    """
    Verifica se todos os arquivos .txt correspondentes aos .mp3 estão presentes,
    sem pular números.
    Ex: ['a_part1.mp3', 'a_part2.mp3'] e ['a_part1.txt', 'a_part2.txt'] -> True
    Ex: ['a_part1.mp3', 'a_part2.mp3'] e ['a_part1.txt'] -> False (falta part2)
    Ex: ['a_part1.mp3', 'a_part3.mp3'] e ['a_part1.txt', 'a_part3.txt'] -> False (pulou part2)
    """
    # Extrai os números das partes dos arquivos .mp3
    mp3_part_numbers = [int(re.search(r'_part(\d+)\.mp3$', f).group(1)) for f in sorted_mp3_parts]
    
    # Extrai os números das partes dos arquivos .txt
    txt_part_numbers = [int(re.search(r'_part(\d+)\.txt$', f).group(1)) for f in sorted_txt_parts]

    # Verifica se a sequência de números de .mp3 é contínua (1, 2, 3, ...)
    if not mp3_part_numbers or mp3_part_numbers != list(range(1, len(mp3_part_numbers) + 1)):
        logger.warning(f"[MERGE] Sequência de partes .mp3 não é contínua ou vazia para {sorted_mp3_parts[0] if sorted_mp3_parts else 'N/A'}.")
        return False

    # Verifica se os números de .txt são exatamente os mesmos que os de .mp3
    return mp3_part_numbers == txt_part_numbers

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
        # TODO: O idioma pode ser dinâmico ou detectado. Aqui está fixo como exemplo.
        result = model.transcribe(mp3_file_path, verbose=False, fp16=False, language="pt") # Assumindo idioma português.
        
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

def check_and_merge_transcriptions(course_folder, module_item, base_name, module_path, module_output_parts_path, module_output_path):
    """
    Verifica se todas as partes de uma transcrição estão presentes, as mescla e limpa os temporários.
    """
    try:
        logger.info(f"[MERGE] Verificando se é possível fazer merge para: {base_name}")
        
        # 1. Encontrar todas as partes .mp3 originais (para verificar sequência)
        all_mp3_parts = get_sorted_part_files(module_path, base_name)
        
        # 2. Encontrar todas as partes .txt transcritoas
        all_txt_parts = get_sorted_transcribed_part_files(module_output_parts_path, base_name)
        
        # 3. Verificar se todas as partes estão presentes
        if are_all_parts_present(all_mp3_parts, all_txt_parts):
            logger.info(f"[MERGE] Todas as partes presentes para {base_name}. Iniciando merge...")
            
            merged_content = ""
            txt_files_to_delete = []
            mp3_files_to_delete = [] # Lista para arquivos .mp3 originais
            
            # 4. Ler o conteúdo de cada parte .txt em ordem e concatenar
            for txt_file in all_txt_parts:
                txt_file_path = os.path.join(module_output_parts_path, txt_file)
                try:
                    with open(txt_file_path, 'r', encoding='utf-8') as f:
                        merged_content += f.read() + "\n\n" # Adiciona duas quebras de linha entre partes
                    txt_files_to_delete.append(txt_file_path)
                    logger.debug(f"[MERGE] Conteúdo de {txt_file} adicionado ao merge.")
                except Exception as e:
                    logger.error(f"[MERGE] Erro ao ler {txt_file_path} para merge: {e}")
                    return False # Se falhar em ler uma parte, aborta o merge

            # 5. Salvar o conteúdo mesclado em um único arquivo .txt na pasta /output
            final_output_filename = f"{base_name}.txt"
            final_output_path = os.path.join(module_output_path, final_output_filename)
            
            try:
                with open(final_output_path, 'w', encoding='utf-8') as f:
                    f.write(merged_content.strip()) # .strip() remove possíveis quebras extras no final
                logger.info(f"[MERGE] Merge concluído e salvo em: {final_output_path}")
                
                # 6. Limpeza: Apagar os arquivos .txt de partes após o merge bem-sucedido
                for txt_file_path in txt_files_to_delete:
                    try:
                        os.remove(txt_file_path)
                        logger.debug(f"[CLEANUP] Arquivo temporário .txt removido: {txt_file_path}")
                    except Exception as e:
                         logger.warning(f"[CLEANUP] Erro ao remover {txt_file_path}: {e}")
                
                # 7. Limpeza: Apagar os arquivos .mp3 originais também
                for mp3_file in all_mp3_parts:
                    mp3_file_path = os.path.join(module_path, mp3_file)
                    mp3_files_to_delete.append(mp3_file_path)
                
                for mp3_file_path in mp3_files_to_delete:
                    try:
                        os.remove(mp3_file_path)
                        logger.debug(f"[CLEANUP] Arquivo original .mp3 removido: {mp3_file_path}")
                    except Exception as e:
                         logger.warning(f"[CLEANUP] Erro ao remover {mp3_file_path}: {e}")

                # 8. Limpeza Avançada: Verificar e remover pastas vazias em /output_parts
                try:
                    # a. Tenta remover a pasta do módulo em /output_parts se ela estiver vazia
                    if not any(os.scandir(module_output_parts_path)):
                        os.rmdir(module_output_parts_path) # os.rmdir só remove diretórios vazios
                        logger.info(f"[CLEANUP] Pasta vazia em output_parts removida: {module_output_parts_path}")
                    else:
                        logger.debug(f"[CLEANUP] Pasta em output_parts não está vazia, mantendo: {module_output_parts_path}")

                except Exception as e:
                    logger.warning(f"[CLEANUP] Erro durante verificação/remoção de pastas vazias em output_parts: {e}")

                logger.info(f"[CLEANUP] Limpeza de arquivos temporários concluída para {base_name}.")
                
                return True
            except Exception as e:
                logger.error(f"[MERGE] Erro ao salvar o arquivo mergeado {final_output_path}: {e}")
                return False
        else:
            logger.info(f"[MERGE] Nem todas as partes estão prontas ou a sequência está incompleta para {base_name}. Aguardando...")
            return False
    except Exception as e:
        logger.error(f"[MERGE] Erro durante a verificação de merge para {base_name}: {e}", exc_info=True)
        return False

def worker_gdrive(model):
    """Worker para monitorar e processar arquivos do Google Drive."""
    logger.info(f"[WORKER-GDRIVE] Iniciado. Monitorando pasta: {INPUT_GDRIVE_FOLDER}")
    while True:
        try:
            # --- Atualiza status para 'waiting' ---
            global_state_manager.update_worker_status("worker_gdrive", "waiting", queue_size=0)
            # -------------------------------------
            
            logger.info("[WORKER-GDRIVE] Verificando arquivos para processamento...")
            # TODO: Implementar lógica real de varredura e transcrição completa (similar ao worker_web)
            # Esta é a próxima grande etapa após worker_web estar 100%
            
            # --- Simulação de verificação e atualização de fila ---
            # Esta parte é temporária até a lógica real ser implementada
            simulated_queue_size = 0
            if os.path.exists(INPUT_GDRIVE_FOLDER):
                # Conta cursos (pastas) como itens na fila para simulação
                simulated_queue_size = len([d for d in os.listdir(INPUT_GDRIVE_FOLDER) if os.path.isdir(os.path.join(INPUT_GDRIVE_FOLDER, d))])
            
            global_state_manager.update_worker_status("worker_gdrive", "waiting", queue_size=simulated_queue_size)
            # -------------------------------------------------------
            
            time.sleep(2) # Simulação de trabalho
            logger.debug("[WORKER-GDRIVE] Verificação concluída.")
            
        except Exception as e:
            logger.error(f"[WORKER-GDRIVE] Erro no worker: {e}")
            # Em caso de erro, atualiza status
            global_state_manager.update_worker_status("worker_gdrive", "error", current_item=str(e)[:50])
            
        time.sleep(POLLING_INTERVAL) # Espera o intervalo definido

def worker_web(model):
    """Worker para monitorar e processar uploads da WebUI."""
    logger.info(f"[WORKER-WEB] Iniciado. Monitorando pasta: {INPUT_WEB_FOLDER}")
    while True:
        try:
            # --- Atualiza status para 'waiting' ---
            global_state_manager.update_worker_status("worker_web", "waiting", queue_size=0) # Inicializa tamanho da fila
            # -------------------------------------
            
            logger.info("[WORKER-WEB] Verificando arquivos para processamento...")
            
            items_to_process = [] # Para contar itens
            
            # 1. Varre a pasta INPUT_WEB_FOLDER
            if os.path.exists(INPUT_WEB_FOLDER):
                for item in os.listdir(INPUT_WEB_FOLDER):
                    item_path = os.path.join(INPUT_WEB_FOLDER, item)
                    
                    # 2. Verifica se é um diretório (representando um "curso" ou "upload")
                    if os.path.isdir(item_path):
                        items_to_process.append(item) # Conta o curso
                        # ... (restante da lógica de processamento)
                        
                        # 3. Varre os subdiretórios (módulos)
                        for module_item in os.listdir(item_path):
                            module_path = os.path.join(item_path, module_item)
                            
                            # 4. Verifica se é um diretório (representando um "módulo")
                            if os.path.isdir(module_path):
                                
                                # 5. Varre os arquivos dentro do módulo
                                for audio_file in os.listdir(module_path):
                                    # 6. Verifica se é um arquivo _part1.mp3 (começa o processo)
                                    if audio_file.endswith("_part1.mp3"):
                                        # ... (restante da lógica)
                                        
                                        # --- Atualiza status para 'processing' ---
                                        global_state_manager.update_worker_status("worker_web", "processing", current_item=f"{item}/{module_item}/{base_name}")
                                        # ---------------------------------------
                                        
                                        # ... (lógica de transcrição e merge)
                                        
                                        if merge_success:
                                            logger.info(f"[WORKER-WEB] Processo completo (transcrição, merge e limpeza) para {base_name}.")
                                            # Incrementa métrica
                                            global_state_manager.increment_metric("total_files_processed")
                                            # ... (restante da lógica de conclusão)
                                            if not any(os.scandir(course_path)):
                                                global_state_manager.increment_metric("total_courses_completed")
                                                # ...
                                        
                                        # Após processar, volta para 'waiting'
                                        global_state_manager.update_worker_status("worker_web", "waiting")
                                        
            # Atualiza o tamanho da fila após a varredura
            global_state_manager.update_worker_status("worker_web", "waiting", queue_size=len(items_to_process))
            logger.debug(f"[WORKER-WEB] Verificação concluída. Itens na fila estimada: {len(items_to_process)}")
            
        except Exception as e:
             logger.error(f"[WORKER-WEB] Erro no worker: {e}", exc_info=True)
             # Em caso de erro, atualiza status
             global_state_manager.update_worker_status("worker_web", "error", current_item=str(e)[:50]) # Limita o tamanho da mensagem de erro
             
        time.sleep(POLLING_INTERVAL) # Espera o intervalo definido
# ----------------------------

def start_uvicorn():
    """Função para iniciar o servidor Uvicorn em uma thread separada."""
    logger.info("Iniciando servidor FastAPI/Uvicorn...")
    # Configura o Uvicorn para rodar o app FastAPI
    # host="0.0.0.0" permite acesso de fora do container
    # port=8000 é a porta padrão exposta no Dockerfile
    # log_level="info" para logs do servidor
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

def main():
    """Função principal que inicia o aplicativo."""
    logger.info("Iniciando aplicação Whisper Transcription...")
    
    # 1. Carrega o modelo Whisper (uma única vez)
    try:
        model = load_whisper_model()
    except Exception as e:
        logger.critical(f"Não foi possível iniciar a aplicação devido a um erro no carregamento do modelo: {e}")
        return

    # 2. Inicia o servidor FastAPI/Uvicorn em uma thread separada
    logger.info("Iniciando servidor web em thread...")
    web_thread = threading.Thread(target=start_uvicorn, name="WebServer", daemon=True)
    web_thread.start()
    logger.info("Servidor web iniciado com sucesso.")

    # 3. Inicia os workers em threads separadas
    logger.info("Iniciando workers em threads...")
    thread_gdrive = threading.Thread(target=worker_gdrive, args=(model,), name="Worker-GDrive", daemon=True)
    thread_web = threading.Thread(target=worker_web, args=(model,), name="Worker-Web", daemon=True)
    
    thread_gdrive.start()
    thread_web.start()
    logger.info("Workers iniciados com sucesso.")

    # 4. Mantém a aplicação principal viva
    try:
        logger.info("Aplicação principal em execução. Aguardando workers e servidor web...")
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