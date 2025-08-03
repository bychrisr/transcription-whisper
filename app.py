# ~/apps/whisper-transcription-n8n/app.py
import whisper
import time
import os
import threading
import logging
import re # Para ordenar os arquivos por número da parte
import requests # Para notificações Telegram (manter import para futuro)
import shutil # Para salvar o arquivo uploadado
# --- Importações do FastAPI ---
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
# -----------------------------

# --- Configurações ---
MODEL_NAME = "medium"  # Modelo especificado no PDF
DEVICE = "cpu"         # Como é ARM sem GPU, conforme PDF
POLLING_INTERVAL = 300 # 5 minutos em segundos, conforme PDF
INPUT_GDRIVE_FOLDER = "/input"
INPUT_WEB_FOLDER = "/input_web"
OUTPUT_PARTS_FOLDER = "/output_parts"
OUTPUT_FOLDER = "/output"
LOGS_FOLDER = "/logs"
WEBUI_STATIC_FOLDER = "/app/webui" # Caminho padrão dentro do container

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

# TODO: Adicionar mais endpoints (download, status detalhado) conforme necessário.
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
            # Lógica de processamento do worker GDrive vai aqui
            logger.info("[WORKER-GDRIVE] Verificando arquivos para processamento...")
            # TODO: Implementar lógica real de varredura e transcrição completa (similar ao worker_web)
            # Esta é a próxima grande etapa após worker_web estar 100%
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
                        
                        course_output_path = os.path.join(OUTPUT_FOLDER, course_folder)
                        os.makedirs(course_output_path, exist_ok=True)
                        
                        # 3. Varre os subdiretórios (módulos)
                        for module_item in os.listdir(course_path):
                            module_path = os.path.join(course_path, module_item)
                            
                            # 4. Verifica se é um diretório (representando um "módulo")
                            if os.path.isdir(module_path):
                                logger.debug(f"[WORKER-WEB] Encontrado módulo: {module_item}")
                                
                                # Define o caminho de saída para este módulo
                                module_output_parts_path = os.path.join(course_output_parts_path, module_item)
                                os.makedirs(module_output_parts_path, exist_ok=True)
                                
                                module_output_path = os.path.join(course_output_path, module_item)
                                os.makedirs(module_output_path, exist_ok=True)
                                
                                # 5. Varre os arquivos dentro do módulo
                                for audio_file in os.listdir(module_path):
                                    # 6. Verifica se é um arquivo _part1.mp3 (começa o processo)
                                    if audio_file.endswith("_part1.mp3"):
                                        # Extrai o nome base (ex: 'aula01' de 'aula01_part1.mp3')
                                        base_name = audio_file.rsplit("_part1", 1)[0]
                                        logger.info(f"[WORKER-WEB] Encontrado início de áudio: {base_name}")
                                        
                                        # 7. Encontra todas as partes ordenadas
                                        all_parts = get_sorted_part_files(module_path, base_name)
                                        logger.debug(f"[WORKER-WEB] Partes encontradas para {base_name}: {all_parts}")
                                        
                                        # 8. Transcreve cada parte (se ainda não transcrito)
                                        transcription_happened = False # Flag para saber se alguma transcrição ocorreu
                                        for part_file in all_parts:
                                             part_file_path = os.path.join(module_path, part_file)
                                             # Define o nome do arquivo de saída (.txt)
                                             output_txt_filename = os.path.splitext(part_file)[0] + ".txt"
                                             output_txt_path = os.path.join(module_output_parts_path, output_txt_filename)
                                             
                                             # Verifica se a transcrição já existe para evitar reprocessamento
                                             if not os.path.exists(output_txt_path):
                                                 success = transcribe_part(model, part_file_path, output_txt_path)
                                                 if success:
                                                     logger.info(f"[WORKER-WEB] Transcrição concluída: {part_file}")
                                                     transcription_happened = True
                                                 else:
                                                     logger.error(f"[WORKER-WEB] Falha na transcrição: {part_file}")
                                             else:
                                                 logger.info(f"[WORKER-WEB] Transcrição já existe, pulando: {output_txt_path}")

                                        # --- AQUI VAI A LÓGICA DE VERIFICAÇÃO DE CONCLUSÃO DO CURSO ---
                                        # 9. Após tentar transcrever (ou verificar que já existem),
                                        # verificar se é possível fazer o merge E LIMPAR
                                        # Só tenta merge se houve transcrição OU se é a primeira vez checando
                                        # (para casos onde tudo já estava transcrito)
                                        if transcription_happened or all_parts: # Simplificação: tenta sempre se encontrou partes
                                            merge_success = check_and_merge_transcriptions(
                                                course_folder, module_item, base_name,
                                                module_path, # Passa o caminho do módulo de input também
                                                module_output_parts_path, module_output_path
                                            )
                                            if merge_success:
                                                logger.info(f"[WORKER-WEB] Processo completo (transcrição, merge e limpeza) para {base_name}.")
                                                # --- NOVIDADE: Verificar conclusão do módulo e do curso ---
                                                # Após o merge, verificamos se o diretório do módulo em INPUT_WEB_FOLDER está vazio
                                                # Se estiver, significa que todas as aulas do módulo foram processadas.
                                                try:
                                                    # Verifica se o diretório do módulo está vazio
                                                    if not any(os.scandir(module_path)):
                                                        logger.info(f"[WORKER-WEB] Módulo '{module_item}' do curso '{course_folder}' concluído. Removendo pasta do módulo.")
                                                        
                                                        # Tenta remover o diretório do módulo (e quaisquer subdiretórios vazios)
                                                        try:
                                                            import shutil
                                                            shutil.rmtree(module_path)
                                                            logger.info(f"[CLEANUP] Pasta do módulo '{module_item}' removida com sucesso.")
                                                            
                                                            # Após remover o módulo, verificar se o curso está completo
                                                            # Verifica se o diretório do curso em INPUT_WEB_FOLDER está vazio
                                                            if not any(os.scandir(course_path)):
                                                                logger.info(f"[WORKER-WEB] Curso '{course_folder}' concluído. Removendo pasta do curso.")
                                                                # Tenta remover o diretório do curso
                                                                try:
                                                                    shutil.rmtree(course_path)
                                                                    logger.info(f"[CLEANUP] Pasta do curso '{course_folder}' removida com sucesso.")
                                                                except Exception as e:
                                                                    logger.error(f"[CLEANUP] Erro ao remover pasta do curso '{course_path}': {e}")
                                                                
                                                        except Exception as e:
                                                            logger.error(f"[CLEANUP] Erro ao remover pasta do módulo '{module_path}': {e}")
                                                    else:
                                                        logger.debug(f"[WORKER-WEB] Módulo '{module_item}' do curso '{course_folder}' ainda possui aulas não finalizadas.")
                                                except Exception as e:
                                                    logger.error(f"[WORKER-WEB] Erro durante verificação de conclusão do módulo '{module_item}' do curso '{course_folder}': {e}")
                                                # -------------------------------------------------
                                            else:
                                                logger.info(f"[WORKER-WEB] Merge não realizado para {base_name} (aguardando partes ou sequência incompleta).")

            logger.debug("[WORKER-WEB] Verificação concluída.")
        except Exception as e:
             logger.error(f"[WORKER-WEB] Erro no worker: {e}", exc_info=True) # exc_info=True mostra o stacktrace
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