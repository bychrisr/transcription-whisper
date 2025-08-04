// --- Configuração ---

    const API_BASE_URL = ''; // Caminho base para a API

    // --- Função para Buscar e Atualizar os Cards ---
    async function updateDashboardCards() {
        try {
            console.log("Buscando dados de /api/status/detailed...");
            const response = await fetch(`${API_BASE_URL}/api/status/detailed`);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            console.log("Dados detalhados recebidos:", data);

            // --- Atualizar elementos da página com os dados recebidos ---

            // 1. Métricas Básicas (Filas, Totais)
            if (data.total_transcriptions !== undefined) {
                document.getElementById('metric-total-transcriptions').textContent = data.total_transcriptions;
            }
            if (data.queue_web_size !== undefined) {
                document.getElementById('metric-queue-web').textContent = data.queue_web_size;
            }
            if (data.queue_gdrive_size !== undefined) {
                document.getElementById('metric-queue-gdrive').textContent = data.queue_gdrive_size;
            }

            // 2. Métricas do Sistema (CPU, RAM)
            // Assumindo que os dados de sistema foram incluídos no JSON do endpoint
            if (data.system) {
                document.getElementById('metric-cpu').textContent = data.system.cpu_percent !== undefined ? data.system.cpu_percent : '--';
                document.getElementById('metric-ram').textContent = data.system.memory_percent !== undefined ? data.system.memory_percent : '--';
                document.getElementById('metric-ram-used').textContent = data.system.memory_used_gb !== undefined ? data.system.memory_used_gb : '--';
                document.getElementById('metric-ram-total').textContent = data.system.memory_total_gb !== undefined ? data.system.memory_total_gb : '--';
            } else {
                // Se não vier em 'system', tenta diretamente em 'data'
                 document.getElementById('metric-cpu').textContent = data.cpu_percent !== undefined ? data.cpu_percent : '--';
                 document.getElementById('metric-ram').textContent = data.memory_percent !== undefined ? data.memory_percent : '--';
                 document.getElementById('metric-ram-used').textContent = data.memory_used_gb !== undefined ? data.memory_used_gb : '--';
                 document.getElementById('metric-ram-total').textContent = data.memory_total_gb !== undefined ? data.memory_total_gb : '--';
            }

            // 3. Status Geral (Opcional)
            // Você pode atualizar um elemento com o status geral do sistema
            // const statusElement = document.getElementById('system-status'); // Se tiver um elemento para isso
            // if (statusElement) {
            //     statusElement.textContent = data.status || 'Desconhecido';
            // }

        } catch (error) {
            console.error('Erro ao buscar/atualizar dados do dashboard:', error);
            // Opcional: Mostrar mensagem de erro nos cards ou em um local específico
            // Por exemplo, definir o conteúdo dos cards como 'Erro'
            document.getElementById('metric-total-transcriptions').textContent = 'Erro';
            document.getElementById('metric-queue-web').textContent = 'Erro';
            document.getElementById('metric-queue-gdrive').textContent = 'Erro';
            document.getElementById('metric-cpu').textContent = 'Erro';
            document.getElementById('metric-ram').textContent = 'Erro';
        }
    }

    // --- Inicialização ---
    document.addEventListener('DOMContentLoaded', function() {
        console.log("Página carregada. Iniciando dashboard...");
        
        // 1. Carregar dados iniciais
        updateDashboardCards();

        // 2. Configurar atualização periódica (ex: a cada 10 segundos)
        // Isso substitui a necessidade do SSE para dados básicos, se o SSE ainda não estiver 100% funcional
        const refreshInterval = setInterval(updateDashboardCards, 10000); // 10000 ms = 10 segundos

        // Opcional: Armazenar o intervalId se precisar parar a atualização depois
        // window.dashboardRefreshInterval = refreshInterval;
    });

// --- Funções Auxiliares ---
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function showFeedback(message, type = 'info') {
    const feedbackEl = document.getElementById('upload-feedback');
    feedbackEl.textContent = message;
    feedbackEl.className = type; // Classes CSS para cor (success, error)
}

function updateDateDisplay() {
    const now = new Date();
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    document.getElementById('current-date').textContent = now.toLocaleDateString('pt-BR', options);
}

// --- Inicialização e Conexão SSE ---
document.addEventListener('DOMContentLoaded', function () {
    updateDateDisplay();
    connectSSE(); // Conecta ao Server-Sent Events para dados em tempo real
    loadInitialData(); // Carrega dados iniciais via fetch
    setupUploadArea(); // Configura o componente de upload
});

// --- Conexão SSE para Dados em Tempo Real ---
function connectSSE() {
    if (typeof(EventSource) === "undefined") {
        console.error("SSE não suportado.");
        document.getElementById('system-status').textContent = 'SSE não suportado';
        return;
    }

    const eventSource = new EventSource(`${API_BASE_URL}/api/events`);
    console.log("Conectando ao SSE:", `${API_BASE_URL}/api/events`);

    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            console.log("Dados SSE recebidos:", data);

            // Atualizar métricas gerais
            if (data.system) {
                document.getElementById('metric-cpu').textContent = data.system.cpu_percent !== undefined ? data.system.cpu_percent.toFixed(1) : '--';
                document.getElementById('metric-ram').textContent = data.system.memory_percent !== undefined ? data.system.memory_percent.toFixed(1) : '--';
                document.getElementById('metric-ram-used').textContent = data.system.memory_used_gb !== undefined ? data.system.memory_used_gb.toFixed(2) : '--';
                document.getElementById('metric-ram-total').textContent = data.system.memory_total_gb !== undefined ? data.system.memory_total_gb.toFixed(2) : '--';
            }
            if (data.queue) {
                document.getElementById('metric-total-transcriptions').textContent = data.queue.total_transcriptions !== undefined ? data.queue.total_transcriptions : 0;
                document.getElementById('metric-queue-web').textContent = data.queue.web_size !== undefined ? data.queue.web_size : 0;
                document.getElementById('metric-queue-gdrive').textContent = data.queue.gdrive_size !== undefined ? data.queue.gdrive_size : 0;
            }
            if (data.workers) {
                // Combinar status dos workers para um status geral simples
                const webStatus = data.workers.web?.status || 'Desconhecido';
                const gdriveStatus = data.workers.gdrive?.status || 'Desconhecido';
                const overallStatus = (webStatus === 'running' && gdriveStatus === 'running') ? 'Operacional' : 'Problemas';
                document.getElementById('system-status').textContent = overallStatus;
                // Você pode adicionar lógica mais complexa aqui se quiser mostrar status individuais
            }

        } catch (e) {
            console.error("Erro ao processar evento SSE:", e, event.data);
        }
    };

    eventSource.onerror = function(err) {
        console.error("Erro na conexão SSE:", err);
        document.getElementById('system-status').textContent = 'Erro na conexão';
    };
}

// --- Carregamento de Dados Iniciais via Fetch ---
async function loadInitialData() {
    try {
        // Carregar dados detalhados (incluindo métricas de performance)
        const response = await fetch(`${API_BASE_URL}/api/status/detailed`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        console.log("Dados detalhados carregados:", data);

        // Atualizar métricas de performance
        updatePerformanceMetrics(data.metrics, data.models_in_output);

        // Carregar listas (fila e transcrições concluídas)
        loadProcessingQueue();
        loadCompletedTranscriptions();

    } catch (error) {
        console.error('Erro ao carregar dados iniciais:', error);
        // Mostrar erro em algum lugar?
    }
}

function updatePerformanceMetrics(metrics, modelsInOutput) {
    const perfList = document.getElementById('model-performance-list');
    const avgProcessTimeEl = document.getElementById('avg-process-time');

    if (!metrics) {
        perfList.innerHTML = '<li>Métricas não disponíveis.</li>';
        avgProcessTimeEl.textContent = '-- segundos';
        return;
    }

    // Métricas por modelo
    const avgSpeedPerModel = metrics.avg_transcription_speed_per_model || {};
    if (Object.keys(avgSpeedPerModel).length > 0) {
        let html = '';
        for (const [model, avgSecPerMin] of Object.entries(avgSpeedPerModel)) {
            html += `<li><strong>${model}:</strong> ${avgSecPerMin.toFixed(2)} segundos por minuto de áudio</li>`;
        }
        perfList.innerHTML = html;
    } else {
        perfList.innerHTML = '<li>Nenhuma métrica de modelo disponível ainda.</li>';
    }

    // Tempo médio total
    const avgProcessTime = metrics.avg_process_time_sec;
    if (avgProcessTime !== null && avgProcessTime !== undefined) {
        avgProcessTimeEl.textContent = `${avgProcessTime.toFixed(2)} segundos`;
    } else {
        avgProcessTimeEl.textContent = '-- segundos';
    }
}


// --- Carregar Fila de Processamento ---
async function loadProcessingQueue() {
    // Esta função pode ser mais complexa se você tiver um endpoint que liste arquivos em processamento
    // Por enquanto, vamos simular ou mostrar o tamanho das filas
    // Você pode criar um endpoint que liste arquivos em /input e /input_web que ainda não foram processados
    const queueBody = document.getElementById('processing-queue-body');
    queueBody.innerHTML = '<tr><td colspan="3" class="text-center">Fila dinâmica não implementada. Veja o tamanho nas métricas.</td></tr>';
    // Ou faça um fetch para um endpoint futuro como /api/queue
}

// --- Carregar Transcrições Concluídas ---
async function loadCompletedTranscriptions() {
    const tbody = document.getElementById('completed-transcriptions-body');
    tbody.innerHTML = '<tr><td colspan="3" class="text-center">Carregando...</td></tr>';

    try {
        const response = await fetch(`${API_BASE_URL}/api/transcriptions`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const transcriptions = await response.json();

        if (transcriptions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center">Nenhuma transcrição encontrada.</td></tr>';
            return;
        }

        let html = '';
        transcriptions.forEach(item => {
            html += `
                <tr>
                    <td>${item.name}</td>
                    <td>${formatBytes(item.size)}</td>
                    <td><a href="${API_BASE_URL}/api/download/${encodeURIComponent(item.path)}" target="_blank" class="btn btn-outline-primary btn-sm">Baixar</a></td>
                </tr>
            `;
        });
        tbody.innerHTML = html;

    } catch (error) {
        console.error('Erro ao carregar transcrições:', error);
        tbody.innerHTML = `<tr><td colspan="3" class="text-center text-danger">Erro ao carregar: ${error.message}</td></tr>`;
    }
}

// --- Componente de Upload ---
function setupUploadArea() {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const submitBtn = document.getElementById('submit-btn');

    // Eventos do input file
    fileInput.addEventListener('change', function () {
        const file = this.files[0];
        if (file) {
            showFeedback(`Arquivo selecionado: ${file.name}`, 'info');
            submitBtn.style.display = 'block';
        } else {
            showFeedback('', 'info');
            submitBtn.style.display = 'none';
        }
    });

    // Eventos de clique no botão "Browse"
    document.querySelector('.browse-button').addEventListener('click', () => fileInput.click());

    // Eventos de arrastar e soltar
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => uploadArea.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        uploadArea.addEventListener(eventName, () => uploadArea.classList.remove('dragover'), false);
    });

    // Lidar com o drop
    uploadArea.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length) {
            fileInput.files = files;
            const event = new Event('change');
            fileInput.dispatchEvent(event);
        }
    }

    // Evento do botão de envio
    submitBtn.addEventListener('click', async function () {
        const file = fileInput.files[0];
        if (!file) {
            showFeedback('Nenhum arquivo selecionado.', 'error');
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Enviando...';
        showFeedback('Enviando arquivo...', 'info');

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${API_BASE_URL}/api/upload`, {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const data = await response.json();
                showFeedback(`Upload bem-sucedido: ${data.filename}`, 'success');
                // Limpar seleção
                fileInput.value = '';
                submitBtn.style.display = 'none';
                // Recarregar a lista de transcrições após upload
                setTimeout(loadCompletedTranscriptions, 1000); // Pequeno atraso
            } else {
                const errorData = await response.json();
                showFeedback(`Erro no upload: ${errorData.detail || response.statusText}`, 'error');
            }
        } catch (error) {
            console.error("Erro durante o upload:", error);
            showFeedback(`Erro de rede: ${error.message}`, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Enviar Arquivo';
        }
    });
}