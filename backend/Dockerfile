FROM python:3.9-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    gcc \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Criar script wait-for-it
RUN curl -o /wait-for-it.sh https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh \
    && chmod +x /wait-for-it.sh

# Instalar dependências Python - ordem otimizada
COPY requirements.txt .
RUN pip install --no-cache-dir "numpy<2"

# Instalar PyTorch primeiro (versão compatível)
RUN pip install --no-cache-dir torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu

# Instalar Whisper e outras dependências
RUN pip install --no-cache-dir openai-whisper==20231117
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Criar diretórios de dados
RUN mkdir -p data/input data/input_web data/output data/output_parts data/logs

EXPOSE 8000

CMD ["/wait-for-it.sh", "postgres:5432", "redis:6379", "--", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]