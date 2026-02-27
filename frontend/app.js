cat > frontend/app.js << 'ENDOFFILE'
let accessToken = null;
let isAdmin = false;
let uploadedFiles = [];
const API_BASE = '/api';

document.addEventListener('DOMContentLoaded', () => {
    const savedToken = localStorage.getItem('accessToken');
    if (savedToken) {
        accessToken = savedToken;
        isAdmin = localStorage.getItem('isAdmin') === 'true';
        showMainScreen();
    } else {
        showLoginScreen();
    }
    setupEventListeners();
});

function setupEventListeners() {
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    document.getElementById('logout-btn').addEventListener('click', logout);
    document.getElementById('admin-logout-btn').addEventListener('click', logout);

    const fileUploadArea = document.getElementById('file-upload-area');
    fileUploadArea.addEventListener('click', () => document.getElementById('file-input').click());
    fileUploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        fileUploadArea.style.borderColor = '#1f4788';
        fileUploadArea.style.backgroundColor = '#f0f4ff';
    });
    fileUploadArea.addEventListener('dragleave', () => {
        fileUploadArea.style.borderColor = '#ddd';
        fileUploadArea.style.backgroundColor = '#fafafa';
    });
    fileUploadArea.addEventListener('drop', handleFileDrop);
    document.getElementById('file-input').addEventListener('change', (e) => {
        uploadedFiles = Array.from(e.target.files);
        updateFileList();
    });
    document.getElementById('clear-files').addEventListener('click', () => {
        uploadedFiles = [];
        updateFileList();
        document.getElementById('file-input').value = '';
    });
    document.getElementById('process-btn').addEventListener('click', handleProcess);
    const adminLink = document.getElementById('admin-link');
    if (adminLink) adminLink.addEventListener('click', showAdminScreen);
    document.getElementById('back-to-main').addEventListener('click', showMainScreen);
}

// ==================== ВХОД ====================
async function handleLogin(e) {
    e.preventDefault();
    const password = document.getElementById('password').value;
    const errorDiv = document.getElementById('login-error');
    errorDiv.style.display = 'none';
    try {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password })
        });
        if (!response.ok) {
            const data = await response.json();
            errorDiv.textContent = data.detail || 'Неверный пароль';
            errorDiv.style.display = 'block';
            return;
        }
        const data = await response.json();
        accessToken = data.access_token;
        isAdmin = data.is_admin;
        localStorage.setItem('accessToken', accessToken);
        localStorage.setItem('isAdmin', isAdmin);
        showMainScreen();
        document.getElementById('login-form').reset();
    } catch (error) {
        errorDiv.textContent = 'Ошибка соединения с сервером';
        errorDiv.style.display = 'block';
    }
}

function logout() {
    accessToken = null;
    isAdmin = false;
    localStorage.removeItem('accessToken');
    localStorage.removeItem('isAdmin');
    showLoginScreen();
}

// ==================== ЭКРАНЫ ====================
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById(screenId).classList.add('active');
}
function showLoginScreen() { showScreen('login-screen'); }
function showMainScreen() {
    showScreen('main-screen');
    document.getElementById('user-type').textContent = isAdmin ? 'Администратор' : 'Пользователь';
    document.getElementById('admin-link').style.display = isAdmin ? 'inline-block' : 'none';
    loadHistory();
}
function showAdminScreen(e) {
    e.preventDefault();
    showScreen('admin-screen');
    loadAdminStats();
    loadAdminRequests();
}

// ==================== ФАЙЛЫ ====================
function handleFileDrop(e) {
    e.preventDefault();
    const fileUploadArea = document.getElementById('file-upload-area');
    fileUploadArea.style.borderColor = '#ddd';
    fileUploadArea.style.backgroundColor = '#fafafa';
    uploadedFiles = Array.from(e.dataTransfer.files);
    updateFileList();
}

function updateFileList() {
    const fileList = document.getElementById('file-list');
    const filesUl = document.getElementById('files-ul');
    if (uploadedFiles.length === 0) { fileList.style.display = 'none'; return; }
    fileList.style.display = 'block';
    filesUl.innerHTML = '';
    uploadedFiles.forEach((file, idx) => {
        const li = document.createElement('li');
        li.innerHTML = `<span>${file.name} (${(file.size / 1024).toFixed(1)} KB)</span>
            <button type="button" class="btn-remove" onclick="removeFile(${idx})">✕</button>`;
        filesUl.appendChild(li);
    });
}

function removeFile(idx) {
    uploadedFiles.splice(idx, 1);
    document.getElementById('file-input').value = '';
    updateFileList();
}

// ==================== ОБРАБОТКА ====================
async function handleProcess() {
    if (uploadedFiles.length === 0) { alert('Пожалуйста, загрузите файлы'); return; }
    const inputType = document.querySelector('input[name="input_type"]:checked');
    if (!inputType) { alert('Пожалуйста, выберите тип входных данных'); return; }
    const outputs = Array.from(document.querySelectorAll('input[name="requested_outputs"]:checked')).map(e => e.value);
    if (outputs.length === 0) { alert('Пожалуйста, выберите результат'); return; }

    const formData = new FormData();
    uploadedFiles.forEach(file => formData.append('files', file));
    formData.append('input_type', inputType.value);
    formData.append('requested_outputs', JSON.stringify(outputs));
    const comment = document.getElementById('user-comment').value;
    if (comment) formData.append('user_comment', comment);

    document.getElementById('process-btn').disabled = true;
    document.getElementById('progress-container').style.display = 'block';
    document.getElementById('no-results').style.display = 'none';
    document.getElementById('status-message').innerHTML = '<div>⏳ Отправка файлов...</div>';
    updateProgressBar(5);

    try {
        const response = await fetch(`${API_BASE}/tasks/process`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${accessToken}` },
            body: formData
        });

        if (!response.ok) {
            let errorMsg = `Ошибка сервера (${response.status})`;
            try { const err = await response.json(); errorMsg = err.detail || errorMsg; } catch(e) {}
            throw new Error(errorMsg);
        }

        const data = await response.json();
        const requestId = data.request_id;
        document.getElementById('status-message').innerHTML = '<div>⏳ Обработка документов...</div>';

        // Поллинг статуса каждые 3 секунды
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            if (attempts > 100) {
                clearInterval(poll);
                document.getElementById('status-message').innerHTML = '<div class="error">Таймаут обработки</div>';
                document.getElementById('process-btn').disabled = false;
                return;
            }
            try {
                const statusRes = await fetch(`${API_BASE}/tasks/status/${requestId}`, {
                    headers: { 'Authorization': `Bearer ${accessToken}` }
                });
                const statusData = await statusRes.json();
                updateProgressBar(Math.min(10 + attempts * 3, 90));

                if (statusData.status === 'success') {
                    clearInterval(poll);
                    updateProgressBar(100);
                    displayResults(statusData.output_files);
                    loadHistory();
                    uploadedFiles = [];
                    updateFileList();
                    document.getElementById('file-input').value = '';
                    document.getElementById('user-comment').value = '';
                    document.getElementById('process-btn').disabled = false;
                } else if (statusData.status === 'error') {
                    clearInterval(poll);
                    document.getElementById('status-message').innerHTML = `<div class="error">Ошибка: ${statusData.error_message}</div>`;
                    document.getElementById('process-btn').disabled = false;
                }
            } catch(e) { console.error('Ошибка поллинга:', e); }
        }, 3000);

    } catch (error) {
        document.getElementById('status-message').innerHTML = `<div class="error">Ошибка: ${error.message}</div>`;
        document.getElementById('process-btn').disabled = false;
    }
}

function updateProgressBar(percent) {
    document.getElementById('progress-fill').style.width = percent + '%';
    const currentStep = Math.ceil((percent / 100) * 4);
    document.querySelectorAll('.step').forEach((step, idx) => {
        step.classList.toggle('active', idx + 1 <= currentStep);
    });
}

function displayResults(outputFiles) {
    const resultsList = document.getElementById('results-list');
    resultsList.innerHTML = '';
    Object.values(outputFiles).forEach(file => {
        const li = document.createElement('li');
        const icon = file.type.includes('excel') ? '📊' : '📄';
        li.innerHTML = `<span class="result-name">${icon} ${file.name}</span>
            <button class="btn btn-success btn-small" onclick="downloadFile('${file.name}')">Скачать</button>`;
        resultsList.appendChild(li);
    });
    document.getElementById('results-container').style.display = 'block';
    document.getElementById('status-message').innerHTML = '<div class="success">✓ Обработка завершена успешно</div>';
}

async function downloadFile(fileName) {
    window.location.href = `${API_BASE}/tasks/download-by-name/${encodeURIComponent(fileName)}`;
}

// ==================== ИСТОРИЯ ====================
async function loadHistory() {
    try {
        const response = await fetch(`${API_BASE}/tasks/history`, {
            headers: { 'Authorization': `Bearer ${accessToken}` }
        });
        if (!response.ok) throw new Error();
        const data = await response.json();
        displayHistory(data.history);
    } catch (error) {
        document.getElementById('history-container').innerHTML = '<div class="error">Ошибка загрузки истории</div>';
    }
}

function displayHistory(history) {
    const container = document.getElementById('history-container');
    if (history.length === 0) { container.innerHTML = '<p class="text-gray">История пуста</p>'; return; }
    let html = '<div class="history-list">';
    history.slice(0, 10).forEach(req => {
        const date = new Date(req.created_at);
        const dateStr = date.toLocaleDateString('ru-RU') + ' ' + date.toLocaleTimeString('ru-RU');
        const statusClass = req.status === 'success' ? 'status-success' : (req.status === 'processing' ? '' : 'status-error');
        const statusText = req.status === 'success' ? 'Успешно' : (req.status === 'processing' ? '⏳ Обработка' : 'Ошибка');
        const filesHtml = req.output_files ? Object.values(req.output_files).map(f =>
            `<button class="btn btn-success btn-small" onclick="downloadFile('${f.name}')">📥 ${f.name}</button>`
        ).join('') : '';
        html += `<div class="history-item">
            <div class="history-header">
                <span class="history-date">${dateStr}</span>
                <span class="status ${statusClass}">${statusText}</span>
            </div>
            <div class="history-details"><span class="history-type">${req.input_type}</span></div>
            ${filesHtml ? `<div style="margin-top:8px">${filesHtml}</div>` : ''}
            ${req.error_message ? `<div class="error" style="margin-top:4px;font-size:12px">${req.error_message}</div>` : ''}
        </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
}

// ==================== АДМИН ====================
async function loadAdminStats() {
    try {
        const response = await fetch(`${API_BASE}/admin/stats`, { headers: { 'Authorization': `Bearer ${accessToken}` } });
        if (!response.ok) throw new Error();
        const data = await response.json();
        document.getElementById('total-requests').textContent = data.total_requests;
        document.getElementById('successful-requests').textContent = data.successful;
        document.getElementById('failed-requests').textContent = data.failed;
        document.getElementById('success-rate').textContent = data.success_rate + '%';
    } catch (error) { console.error('Ошибка загрузки статистики:', error); }
}

async function loadAdminRequests(skip = 0, limit = 50) {
    try {
        const response = await fetch(`${API_BASE}/admin/requests?skip=${skip}&limit=${limit}`, {
            headers: { 'Authorization': `Bearer ${accessToken}` }
        });
        if (!response.ok) throw new Error();
        const data = await response.json();
        const tbody = document.getElementById('admin-table-body');
        tbody.innerHTML = '';
        data.requests.forEach(req => {
            const date = new Date(req.created_at);
            const dateStr = date.toLocaleDateString('ru-RU') + ' ' + date.toLocaleTimeString('ru-RU');
            const files = req.uploaded_files ? req.uploaded_files.map(f => f.name).join(', ') : '-';
            const outputs = req.requested_outputs ? req.requested_outputs.join(', ') : '-';
            const statusClass = req.status === 'success' ? 'status-success' : 'status-error';
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${req.id}</td><td>${dateStr}</td><td>${req.input_type}</td>
                <td>${files}</td><td>${outputs}</td>
                <td><span class="status ${statusClass}">${req.status}</span></td>
                <td><button class="btn btn-small btn-primary" onclick="viewAdminRequest(${req.id})">Подробно</button></td>`;
            tbody.appendChild(tr);
        });
    } catch (error) { console.error('Ошибка загрузки запросов:', error); }
}

async function viewAdminRequest(requestId) {
    try {
        const response = await fetch(`${API_BASE}/admin/request/${requestId}`, {
            headers: { 'Authorization': `Bearer ${accessToken}` }
        });
        if (!response.ok) throw new Error();
        const data = await response.json();
        alert(`Запрос #${data.id}\nСтатус: ${data.status}\nТип: ${data.input_type}\n\nОшибка:\n${data.error_message || '(нет)'}`);
    } catch (error) { console.error('Ошибка:', error); }
}

document.addEventListener('click', (e) => {
    if (e.target.id === 'export-csv-btn') window.location.href = `${API_BASE}/admin/export-csv`;
    if (e.target.id === 'filter-btn') loadAdminRequests();
});
