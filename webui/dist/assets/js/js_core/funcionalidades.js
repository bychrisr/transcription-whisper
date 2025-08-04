// ~/apps/whisper-transcription-n8n/webui/dist/functionalidades.js

// --- Configuração ---
const API_BASE_URL = ''; // Caminho base para a API. Como a API está na mesma origem, pode ser vazio ou '/api'

// --- Funções Auxiliares ---
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function showFeedback(message, type = 'info', targetElementId = 'upload-feedback') {
    const feedbackEl = document.getElementById(targetElementId);
    if (feedbackEl) {
        feedbackEl.textContent = message;
        feedbackEl.className = `alert alert-${type}`; // Classes do Bootstrap para estilo
    }
}

function updateDateDisplay() {
    const now = new Date();
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    const dateElement = document.getElementById('current-date');
    if (dateElement) {
        dateElement.textContent = now.toLocaleDateString('pt-BR', options);
    }
}

// --- Conexão SSE para Dados em Tempo Real ---
function connectSSE() {
    if (typeof(EventSource) === "undefined") {
        console.error("SSE não suportado.");
        const statusEl = document.getElementById('system-status');
        if (statusEl) statusEl.textContent = 'SSE não suportado';
        return;
    }

    const eventSource = new EventSource(`${API_BASE_URL}/api/events`);
    console.log("Conectando ao SSE:", `${API_BASE_URL}/api/events`);

    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            console.log("Evento SSE recebido:", data); // Bom para debug

            // --- Atualizar elementos da página com os dados recebidos ---
            // 1. Métricas do Sistema (CPU, RAM)
            if (data.system) {
                const cpuEl = document.getElementById('metric-cpu');
                const ramEl = document.getElementById('metric-ram');
                const ramUsedEl = document.getElementById('metric-ram-used');
                const ramTotalEl = document.getElementById('metric-ram-total');

                if (cpuEl) {
                    cpuEl.textContent = data.system.cpu_percent !== undefined ? data.system.cpu_percent.toFixed(1) : '--';
                }
                if (ramEl) {
                    ramEl.textContent = data.system.memory_percent !== undefined ? data.system.memory_percent.toFixed(1) : '--';
                }
                if (ramUsedEl) {
                    ramUsedEl.textContent = data.system.memory_used_gb !== undefined ? data.system.memory_used_gb.toFixed(2) : '--';
                }
                if (ramTotalEl) {
                    ramTotalEl.textContent = data.system.memory_total_gb !== undefined ? data.system.memory_total_gb.toFixed(2) : '--';
                }
            }
            // 2. Métricas da Fila
            if (data.queue) {
                const totalTransEl = document.getElementById('metric-total-transcriptions');
                const queueWebEl = document.getElementById('metric-queue-web');
                const queueGdriveEl = document.getElementById('metric-queue-gdrive');

                if (totalTransEl) {
                    totalTransEl.textContent = data.queue.total_transcriptions !== undefined ? data.queue.total_transcriptions : 0;
                }
                if (queueWebEl) {
                    queueWebEl.textContent = data.queue.web_size !== undefined ? data.queue.web_size : 0;
                }
                if (queueGdriveEl) {
                    queueGdriveEl.textContent = data.queue.gdrive_size !== undefined ? data.queue.gdrive_size : 0;
                }
            }
            // 3. Status Geral do Sistema
            const systemStatusEl = document.getElementById('system-status');
            if (data.workers && systemStatusEl) {
                const webStatus = data.workers.web?.status || 'Desconhecido';
                const gdriveStatus = data.workers.gdrive?.status || 'Desconhecido';
                const overallStatus = (webStatus === 'running' && gdriveStatus === 'running') ? 'Operacional' : 'Problemas';
                systemStatusEl.textContent = overallStatus;
            }

        } catch (e) {
            console.error("Erro ao processar evento SSE:", e, "Dados recebidos:", event.data);
        }
    };

    eventSource.onerror = function(err) {
        console.error("Erro na conexão SSE:", err);
        const statusEl = document.getElementById('system-status');
        if (statusEl) {
            statusEl.textContent = 'Erro na conexão';
        }
    };
}

// --- Função para Buscar e Atualizar os Cards (Fallback ou complemento ao SSE) ---
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

        // 2. Métricas do Sistema (CPU, RAM) - Se não vier via SSE
        if (data.system) {
            document.getElementById('metric-cpu').textContent = data.system.cpu_percent !== undefined ? data.system.cpu_percent.toFixed(1) : '--';
            document.getElementById('metric-ram').textContent = data.system.memory_percent !== undefined ? data.system.memory_percent.toFixed(1) : '--';
            document.getElementById('metric-ram-used').textContent = data.system.memory_used_gb !== undefined ? data.system.memory_used_gb.toFixed(2) : '--';
            document.getElementById('metric-ram-total').textContent = data.system.memory_total_gb !== undefined ? data.system.memory_total_gb.toFixed(2) : '--';
        }

        // 3. Métricas de Performance
        updatePerformanceMetrics(data.metrics, data.models_in_output);

    } catch (error) {
        console.error('Erro ao buscar/atualizar dados do dashboard:', error);
        // Opcional: Mostrar mensagem de erro nos cards ou em um local específico
        document.getElementById('metric-total-transcriptions').textContent = 'Erro';
        document.getElementById('metric-queue-web').textContent = 'Erro';
        document.getElementById('metric-queue-gdrive').textContent = 'Erro';
        document.getElementById('metric-cpu').textContent = 'Erro';
        document.getElementById('metric-ram').textContent = 'Erro';
    }
}

function updatePerformanceMetrics(metrics, modelsInOutput) {
    const perfList = document.getElementById('model-performance-list');
    const avgProcessTimeEl = document.getElementById('avg-process-time');

    if (!metrics || !perfList || !avgProcessTimeEl) {
        console.warn("Elementos de métricas de performance não encontrados no DOM.");
        return;
    }

    // Métricas por modelo
    const avgSpeedPerModel = metrics.avg_transcription_speed_per_model || {};
    if (Object.keys(avgSpeedPerModel).length > 0) {
        let html = '';
        for (const [model, avgSecPerMin] of Object.entries(avgSpeedPerModel)) {
            html += `<li><strong>${model}:</strong> ${avgSecPerMin !== null ? avgSecPerMin.toFixed(2) : '--'} segundos por minuto de áudio</li>`;
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

// --- Carregar Transcrições Concluídas ---
async function loadCompletedTranscriptions() {
    const tbody = document.getElementById('completed-transcriptions-body');
    if (!tbody) {
        console.warn("Elemento 'completed-transcriptions-body' não encontrado.");
        return;
    }
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

// --- Componente de Upload (Simples) ---
function setupUploadArea() {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const submitBtn = document.getElementById('submit-btn');

    if (!uploadArea || !fileInput || !submitBtn) {
        console.warn("Elementos do componente de upload não encontrados.");
        return;
    }

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

// --- Funções para Seleção de Modelo ---
async function loadAndPopulateModels() {
    const modelSelect = document.getElementById('whisper-model-select');
    const applyModelBtn = document.getElementById('apply-model-btn');
    const modelFeedback = document.getElementById('model-change-feedback');

    if (!modelSelect || !applyModelBtn) {
        console.warn("Elementos para seleção de modelo não encontrados no DOM.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/api/models`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();

        const availableModels = data.available_models;
        const currentModel = data.current_model;

        // Limpar opções existentes
        modelSelect.innerHTML = '';

        // Adicionar opções
        availableModels.forEach(modelName => {
            const option = document.createElement('option');
            option.value = modelName;
            option.textContent = modelName.charAt(0).toUpperCase() + modelName.slice(1); // Capitaliza a primeira letra
            if (modelName === currentModel) {
                option.selected = true;
            }
            modelSelect.appendChild(option);
        });

        console.log("Lista de modelos carregada:", availableModels);

        // Adicionar evento ao botão de aplicar
        applyModelBtn.onclick = async function() {
            const selectedModel = modelSelect.value;
            if (!selectedModel) {
                if (modelFeedback) modelFeedback.textContent = "Por favor, selecione um modelo.";
                return;
            }

            try {
                const response = await fetch(`${API_BASE_URL}/api/config/model`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ model: selectedModel })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || `Erro ${response.status}`);
                }

                const result = await response.json();
                console.log("Modelo definido:", result);
                if (modelFeedback) {
                    modelFeedback.textContent = result.message;
                    modelFeedback.className = 'alert alert-warning'; // Amarelo para indicar reinicialização
                    modelFeedback.style.display = 'block';
                }
                // Opcional: Desabilitar o botão temporariamente
                // applyModelBtn.disabled = true;
            } catch (error) {
                console.error("Erro ao definir modelo:", error);
                if (modelFeedback) {
                    modelFeedback.textContent = `Erro: ${error.message}`;
                    modelFeedback.className = 'alert alert-danger';
                    modelFeedback.style.display = 'block';
                }
            }
        };

    } catch (error) {
        console.error("Erro ao carregar modelos:", error);
        if (modelFeedback) {
            modelFeedback.textContent = `Erro ao carregar modelos: ${error.message}`;
            modelFeedback.className = 'alert alert-danger';
            modelFeedback.style.display = 'block';
        }
    }
}

// --- Funções para Upload Estruturado (Atualizado) ---
document.addEventListener('DOMContentLoaded', function () {
    const courseSelect = document.getElementById('select-course');
    const newCourseInput = document.getElementById('new-course');
    const moduleSelect = document.getElementById('select-module');
    const newModuleInput = document.getElementById('new-module');
    const fileInput = document.getElementById('structured-file-input');
    const form = document.getElementById('structured-upload-form');
    const feedback = document.getElementById('structured-upload-feedback');

    if (!courseSelect || !newCourseInput || !moduleSelect || !newModuleInput || !fileInput || !form || !feedback) {
         console.warn("Elementos do formulário de upload estruturado não encontrados.");
         return;
    }

    // Função para mostrar feedback
    function showStructuredFeedback(message, type = 'info') {
        feedback.textContent = message;
        feedback.className = `alert alert-${type}`; // Usa classes do Bootstrap para estilo
    }

    // 1. Carregar lista de cursos ao carregar a página
    async function loadCourses() {
        try {
            const response = await fetch(`${API_BASE_URL}/api/courses`);
            if (!response.ok) {
                if (response.status === 404) {
                     // Se o endpoint não existir, popula com opções padrão ou deixa vazio
                     console.warn("Endpoint /api/courses não encontrado. Populando manualmente.");
                     courseSelect.innerHTML = '<option value="">-- Nenhum curso encontrado --</option>';
                     return;
                }
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const courses = await response.json();
            courseSelect.innerHTML = '<option value="">-- Selecione um Curso --</option>';
            // Adiciona uma opção para "Criar Novo Curso" se desejado, mas vamos usar o input text
            courses.forEach(course => {
                const option = document.createElement('option');
                option.value = course;
                option.textContent = course;
                courseSelect.appendChild(option);
            });
        } catch (error) {
            console.error("Erro ao carregar cursos:", error);
            showStructuredFeedback("Erro ao carregar lista de cursos.", 'danger');
        }
    }

    // Carregar módulos quando um curso for selecionado
courseSelect.addEventListener('change', async function() {
    const selectedCourse = this.value;
    moduleSelect.innerHTML = '<option value="">-- Selecione um Módulo --</option>';
    newModuleInput.disabled = !selectedCourse;
    moduleSelect.disabled = !selectedCourse;

    // Se nenhum curso for selecionado, não faz nada
    if (!selectedCourse) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/courses/${encodeURIComponent(selectedCourse)}/modules`);
        if (!response.ok) {
            if (response.status === 404) {
                console.warn(`Nenhum módulo encontrado para o curso ${selectedCourse} ou endpoint não disponível.`);
                moduleSelect.innerHTML = '<option value="">-- Nenhum módulo encontrado --</option>';
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const modules = await response.json();
        if (modules.length > 0) {
            modules.forEach(module => {
                const option = document.createElement('option');
                option.value = module;
                option.textContent = module;
                moduleSelect.appendChild(option);
            });
        } else {
            moduleSelect.innerHTML = '<option value="">-- Nenhum módulo encontrado --</option>';
        }
    } catch (error) {
        console.error(`Erro ao carregar módulos para ${selectedCourse}:`, error);
        showStructuredFeedback(`Erro ao carregar módulos para ${selectedCourse}.`, 'danger');
    }
});

    // 3. Lógica do formulário de upload
    form.addEventListener('submit', async function(e) {
        e.preventDefault();

        const selectedCourse = courseSelect.value.trim();
        const newCourse = newCourseInput.value.trim();
        const selectedModule = moduleSelect.value.trim();
        const newModule = newModuleInput.value.trim();
        const files = fileInput.files;

        let targetCourse = selectedCourse || newCourse;
        let targetModule = selectedModule || newModule;

        // Validação
        if (!targetCourse) {
            showStructuredFeedback("Por favor, selecione um curso existente ou digite o nome de um novo.", 'warning');
            return;
        }
        if (!targetModule) {
            showStructuredFeedback("Por favor, selecione um módulo existente ou digite o nome de um novo.", 'warning');
            return;
        }
        if (files.length === 0) {
            showStructuredFeedback("Por favor, selecione pelo menos um arquivo.", 'warning');
            return;
        }

        // Desabilitar botão e mostrar feedback
        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        showStructuredFeedback("Enviando arquivos...", 'info');

        // Enviar arquivos um por um
        let allSuccess = true;
        let successCount = 0;
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const formData = new FormData();
            formData.append('file', file);
            // Adicionar metadados como campos extras
            formData.append('course', targetCourse);
            formData.append('module', targetModule);

            try {
                const response = await fetch(`${API_BASE_URL}/api/upload_structured`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || `Erro ${response.status}`);
                }
                const data = await response.json();
                console.log(`Arquivo ${file.name} enviado com sucesso:`, data);
                successCount++;
                // Atualizar feedback parcialmente?
                showStructuredFeedback(`Enviando: ${successCount}/${files.length} arquivos...`, 'info');
            } catch (error) {
                console.error(`Erro ao enviar ${file.name}:`, error);
                showStructuredFeedback(`Erro ao enviar ${file.name}: ${error.message}`, 'danger');
                allSuccess = false;
                // Não interrompe o loop, tenta enviar os próximos
            }
        }

        if (allSuccess) {
            showStructuredFeedback(`${successCount} arquivo(s) enviado(s) com sucesso para '${targetCourse}' -> '${targetModule}'!`, 'success');
            // Limpar formulário após sucesso?
            // form.reset();
            // moduleSelect.innerHTML = '<option value="">-- Selecione um Curso Primeiro --</option>';
            // moduleSelect.disabled = true;
            // newModuleInput.disabled = true;
            // Recarregar listas?
            loadCourses(); // Recarrega a lista de cursos
            // Se o curso selecionado ainda for o mesmo, recarrega os módulos
            if (courseSelect.value === targetCourse) {
                 // Dispara o evento change para recarregar os módulos
                 courseSelect.dispatchEvent(new Event('change'));
            }
        } else {
             showStructuredFeedback(`Alguns arquivos (${files.length - successCount} de ${files.length}) não puderam ser enviados. Veja os erros acima.`, 'danger');
        }
        submitBtn.disabled = false;
    });

    // --- Lógica adicional para facilitar a criação ---
    // Quando o usuário digita um novo curso, limpa a seleção existente
    newCourseInput.addEventListener('input', function() {
        if (this.value.trim() !== '') {
            courseSelect.value = '';
            // Limpa o módulo também
            moduleSelect.innerHTML = '<option value="">-- Selecione um Curso Primeiro --</option>';
            moduleSelect.disabled = true;
            newModuleInput.disabled = true;
            newModuleInput.value = '';
        }
    });

    // Quando o usuário digita um novo módulo, limpa a seleção existente
    newModuleInput.addEventListener('input', function() {
        if (this.value.trim() !== '') {
            moduleSelect.value = '';
        }
    });

    // Quando um curso é selecionado, limpa o input de novo curso
    courseSelect.addEventListener('change', function() {
        if (this.value !== '') {
            newCourseInput.value = '';
        }
    });

    // Quando um módulo é selecionado, limpa o input de novo módulo
    moduleSelect.addEventListener('change', function() {
        if (this.value !== '') {
            newModuleInput.value = '';
        }
    });


    // Inicializar
    loadCourses();
});
// --- Fim das Funções para Upload Estruturado ---

// --- Inicialização ---
document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM totalmente carregado. Iniciando lógica do dashboard...");
    updateDateDisplay();
    connectSSE(); // Conecta ao Server-Sent Events para dados em tempo real
    updateDashboardCards(); // Carrega dados iniciais via fetch
    setupUploadArea(); // Configura o componente de upload
    loadAndPopulateModels(); // Carrega e popula o select de modelos
    loadCompletedTranscriptions(); // Carrega a lista de transcrições concluídas

    // Configurar atualização periódica (ex: a cada 10 segundos) como fallback
    setInterval(updateDashboardCards, 10000); // 10000 ms = 10 segundos
    setInterval(loadCompletedTranscriptions, 30000); // 30 segundos
});