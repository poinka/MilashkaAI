document.addEventListener('DOMContentLoaded', () => {
    // Initialize text elements with translations
    function getMsg(key) {
        return chrome.i18n.getMessage(key) || key;
    }

    // Update all static UI elements with translations
    document.title = getMsg('extName');
    document.querySelector('h1').textContent = getMsg('extName');
    document.querySelector('.drop-zone-text').innerHTML = `
        ${getMsg('dropFilesHere')}<br>
        <small>${getMsg('supportedFormats')}</small>
    `;
    
    // UI Elements
    const uploadForm = document.getElementById('upload-form');
    const fileInput = document.getElementById('file-input');
    const dropZone = document.getElementById('drop-zone');
    const uploadButton = document.getElementById('upload-button');
    const progressBar = document.querySelector('.progress-bar');
    const progressText = document.querySelector('.progress-text');
    const progressContainer = document.getElementById('upload-progress');
    const docList = document.getElementById('document-list');
    const statusFilter = document.getElementById('status-filter');
    const searchInput = document.getElementById('search-docs');
    const voiceToggle = document.getElementById('voice-toggle');
    const voiceFeedback = document.getElementById('voice-feedback');

    // Update placeholder texts
    if (searchInput) {
        searchInput.placeholder = getMsg('searchDocs');
    }

    // Update status filter options
    if (statusFilter) {
        statusFilter.innerHTML = `
            <option value="all">${getMsg('statusAll')}</option>
            <option value="processing">${getMsg('statusProcessing')}</option>
            <option value="indexed">${getMsg('statusIndexed')}</option>
            <option value="error">${getMsg('statusError')}</option>
        `;
    }

    let selectedFiles = new Set();
    let isUploading = false;
    let isRecording = false;

    // --- Drag and Drop Handling ---
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.remove('drag-over');
        });
    });

    dropZone.addEventListener('drop', handleDrop);
    dropZone.addEventListener('click', () => fileInput.click());

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleFiles(files);
    }

    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });

    function handleFiles(files) {
        if (isUploading) return;

        const validFiles = Array.from(files).filter(file => {
            const ext = file.name.toLowerCase().split('.').pop();
            return ['pdf', 'docx', 'txt', 'md'].includes(ext);
        });

        if (validFiles.length === 0) {
            showError(getMsg('errorNoValidFiles'));
            return;
        }

        selectedFiles = new Set(validFiles);
        updateUploadButton();
        showFileList();
    }

    function updateUploadButton() {
        uploadButton.disabled = selectedFiles.size === 0;
        uploadButton.textContent = getMsg('uploadButtonText').replace('{count}', selectedFiles.size);
    }

    function showFileList() {
        const fileList = document.createElement('div');
        fileList.className = 'selected-files';
        selectedFiles.forEach(file => {
            const fileItem = document.createElement('div');
            fileItem.className = 'selected-file';
            fileItem.innerHTML = `
                <span>${file.name}</span>
                <button class="remove-file" data-name="${file.name}">&times;</button>
            `;
            fileList.appendChild(fileItem);
        });
        
        const existingList = dropZone.querySelector('.selected-files');
        if (existingList) {
            dropZone.removeChild(existingList);
        }
        dropZone.appendChild(fileList);

        fileList.querySelectorAll('.remove-file').forEach(button => {
            button.onclick = (e) => {
                e.stopPropagation();
                const fileName = button.dataset.name;
                selectedFiles = new Set(Array.from(selectedFiles).filter(f => f.name !== fileName));
                updateUploadButton();
                showFileList();
            };
        });
    }

    uploadForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (isUploading || selectedFiles.size === 0) return;

        isUploading = true;
        uploadButton.disabled = true;
        progressContainer.style.display = 'block';
        
        try {
            for (const file of selectedFiles) {
                await uploadFile(file);
            }
            
            showSuccess(getMsg('uploadSuccess'));
            selectedFiles.clear();
            updateUploadButton();
            showFileList();
            loadDocumentList();
            
        } catch (error) {
            showError(getMsg('uploadError') + ': ' + error.message);
        } finally {
            isUploading = false;
            progressContainer.style.display = 'none';
        }
    });

    async function uploadFile(file) {
        const reader = new FileReader();
        return new Promise((resolve, reject) => {
            reader.onload = async (e) => {
                if (!(e.target.result instanceof ArrayBuffer)) {
                    reject(new Error(getMsg('errorFileRead')));
                    return;
                }
                const uint8Array = new Uint8Array(e.target.result);

                try {
                    const response = await chrome.runtime.sendMessage({
                        type: "UPLOAD_DOCUMENT",
                        filename: file.name,
                        filetype: file.type,
                        fileData: Array.from(uint8Array)
                    });
                    if (response.success) {
                        updateProgress((Array.from(selectedFiles).indexOf(file) + 1) / selectedFiles.size * 100);
                        resolve(response);
                    } else {
                        reject(new Error(response.error));
                    }
                } catch (error) {
                    reject(error);
                }
            };
            reader.onerror = () => reject(new Error(getMsg('errorFileRead')));
            reader.readAsArrayBuffer(file);
        });
    }

    function updateProgress(percent) {
        progressBar.style.width = `${percent}%`;
        progressText.textContent = `${Math.round(percent)}%`;
    }

    async function loadDocumentList() {
        if (!docList) return;

        try {
            const response = await chrome.runtime.sendMessage({ type: "LIST_DOCUMENTS" });
            console.log('LIST_DOCUMENTS response:', response);
            const documents = Array.isArray(response) ? response : response.documents;

            if (Array.isArray(documents)) {
                renderDocumentList(documents);
            } else {
                showError(getMsg('errorLoadDocs'));
                console.error('Invalid documents array:', documents);
                docList.innerHTML = `<li class="no-documents">${getMsg('errorLoadDocs')}</li>`;
            }
        } catch (error) {
            showError(getMsg('errorLoadDocs') + ': ' + error.message);
            console.error('Load documents error:', error);
            docList.innerHTML = `<li class="no-documents">${getMsg('errorLoadDocs')}</li>`;
        }
    }

    function renderDocumentList(documents) {
        if (!Array.isArray(documents)) {
            console.error('Invalid documents data:', documents);
            docList.innerHTML = `<li class="no-documents">${getMsg('errorLoadDocs')}</li>`;
            return;
        }
    
        const filteredDocs = filterDocuments(documents);
        docList.innerHTML = '';
    
        if (filteredDocs.length === 0) {
            docList.innerHTML = `<li class="no-documents">${getMsg('noDocuments')}</li>`;
            return;
        }
    
        filteredDocs.forEach(doc => {
            const li = document.createElement('li');
            li.innerHTML = `
                <div class="doc-info">
                    <span class="doc-name">${doc.filename}</span>
                    <span class="status-badge status-${doc.status}">${getMsg('status' + doc.status.charAt(0).toUpperCase() + doc.status.slice(1))}</span>
                </div>
                <button class="delete-doc" data-id="${doc.doc_id}" title="${getMsg('deleteDocument')}">&times;</button>
            `;
            docList.appendChild(li);
        });

        docList.querySelectorAll('.delete-doc').forEach(button => {
            button.onclick = async () => {
                try {
                    console.log(`Deleting document ${button.dataset.id}...`);
                    const response = await chrome.runtime.sendMessage({
                        type: "DELETE_DOCUMENT",
                        doc_id: button.dataset.id
                    });
                    console.log(`Received delete response:`, response);
                    if (response.success) {
                        loadDocumentList();
                    } else {
                        showError(getMsg('errorDeleteDoc') + ': ' + response.error);
                    }
                } catch (error) {
                    console.error(`Error deleting document:`, error);
                    showError(getMsg('errorDeleteDoc') + ': ' + error.message);
                }
            };
        });
    }

    function filterDocuments(documents) {
        if (!Array.isArray(documents)) return [];
        
        const status = statusFilter?.value || 'all';
        const search = searchInput?.value?.toLowerCase() || '';
        
        return documents.filter(doc => {
            if (!doc) return false;
            const matchesStatus = status === 'all' || doc.status === status;
            const matchesSearch = doc.filename?.toLowerCase()?.includes(search);
            return matchesStatus && matchesSearch;
        });
    }

    // --- Voice Input Handling ---
    let popupMediaRecorder = null;
    let popupAudioChunks = [];

    voiceToggle?.addEventListener('click', async () => {
        if (isRecording) {
            stopPopupVoiceInput();
        } else {
            startPopupVoiceInput();
        }
    });

    function updateVoiceToggleIcon(isRecording) {
        const icon = voiceToggle.querySelector('.voice-icon');
        if (!icon) return;
        if (isRecording) {
            icon.src = '../icons/stop.png';
            icon.alt = 'Стоп';
        } else {
            icon.src = '../icons/microphone.png';
            icon.alt = 'Микрофон';
        }
    }

    async function startPopupVoiceInput() {
        try {
            // Hide feedback bar at start
            voiceFeedback.style.display = 'none';
            voiceFeedback.textContent = '';

            const stream = await navigator.mediaDevices.getUserMedia({ 
                audio: {
                    channelCount: 1,
                    sampleRate: 16000
                }
            });
            
            // Try to use the most widely supported codecs
            let mimeType = 'audio/webm;codecs=opus';
            if (!MediaRecorder.isTypeSupported(mimeType)) {
                mimeType = 'audio/webm';
                if (!MediaRecorder.isTypeSupported(mimeType)) {
                    mimeType = 'audio/ogg;codecs=opus';
                }
            }
            
            popupAudioChunks = [];
            popupMediaRecorder = new MediaRecorder(stream, { 
                mimeType: mimeType,
                audioBitsPerSecond: 128000 
            });
            popupMediaRecorder.onstart = () => {
                isRecording = true;
                voiceToggle.classList.add('recording');
                voiceToggle.querySelector('.voice-status').textContent = 'Остановить запись';
                updateVoiceToggleIcon(true);
                voiceFeedback.style.display = 'block';
                logPopup('Recording started.');
            };
            popupMediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    popupAudioChunks.push(event.data);
                    logPopup(`Audio chunk captured: ${event.data.size} bytes`);
                }
            };
            popupMediaRecorder.onerror = (e) => {
                logPopup('MediaRecorder error: ' + e.error, 'error');
                showError('Ошибка записи: ' + e.error);
            };
            popupMediaRecorder.onstop = async () => {
                isRecording = false;
                voiceToggle.classList.remove('recording');
                voiceToggle.querySelector('.voice-status').textContent = 'Начать голосовой ввод';
                updateVoiceToggleIcon(false);
                logPopup('Recording stopped. Sending audio for transcription...');
                // Show feedback bar for recognition
                voiceFeedback.textContent = 'Распознавание...';
                voiceFeedback.style.display = 'block';
                voiceFeedback.classList.add('show');
                const audioBlob = new Blob(popupAudioChunks, { type: 'audio/webm' });
                const arrayBuffer = await audioBlob.arrayBuffer();
                try {
                    chrome.runtime.sendMessage({
                        type: 'TRANSCRIBE_AUDIO',
                        audioData: Array.from(new Uint8Array(arrayBuffer)),
                        audioType: 'audio/webm',
                        language: document.documentElement.lang || 'ru'
                    }, async (response) => {
                        try {
                            if (response && response.transcription) {
                                // Show formatting animation
                                voiceFeedback.textContent = 'Форматирование...';
                                voiceFeedback.style.display = 'block';
                                voiceFeedback.classList.add('show');
                                // Send transcription to LLM for formatting
                                chrome.runtime.sendMessage({
                                    type: 'FORMAT_TRANSCRIPTION',
                                    text: response.transcription,
                                    language: document.documentElement.lang || 'ru'
                                }, (formatResp) => {
                                if (formatResp && formatResp.success && formatResp.formatted_text) {
                                    // Success case - show the formatted text
                                    voiceFeedback.textContent = formatResp.formatted_text;
                                    voiceFeedback.style.display = 'block';
                                    voiceFeedback.classList.add('show');
                                    logPopup('Formatting succeeded, showing formatted text');
                                } else {
                                    // Error case - handle and show appropriate error message
                                    const errorMsg = formatResp && formatResp.error ? formatResp.error : 'Unknown error';
                                    logPopup('Formatting failed: ' + errorMsg, 'error');
                                    showError('Ошибка форматирования: ' + errorMsg);
                                    
                                    // Fallback to showing unformatted text with warning
                                    voiceFeedback.textContent = response.transcription + ' [Без форматирования]';
                                    voiceFeedback.style.display = 'block';
                                    voiceFeedback.classList.add('show');
                                }
                                });
                            } else {
                                logPopup('Transcription failed: ' + (response && response.error ? response.error : 'Unknown error'), 'error');
                                showError('Ошибка распознавания: ' + (response && response.error ? response.error : 'Неизвестная ошибка'));
                                voiceFeedback.textContent = 'Ошибка распознавания.';
                                voiceFeedback.style.display = 'block';
                                voiceFeedback.classList.add('show');
                            }
                        } catch (callbackError) {
                            logPopup('Error handling transcription response: ' + callbackError.message, 'error');
                            voiceFeedback.textContent = 'Ошибка обработки результата.';
                            voiceFeedback.style.display = 'block';
                            voiceFeedback.classList.add('show');
                        }
                    });
                } catch (sendError) {
                    logPopup('Error sending audio for transcription: ' + sendError.message, 'error');
                    voiceFeedback.textContent = 'Ошибка отправки аудио.';
                    voiceFeedback.style.display = 'block';
                    voiceFeedback.classList.add('show');
                }
            };
            popupMediaRecorder.start();
        } catch (error) {
            logPopup('Microphone access denied or error: ' + error.message, 'error');
            voiceFeedback.textContent = 'Нет доступа к микрофону.';
            voiceFeedback.style.display = 'block';
            voiceFeedback.classList.add('show');
            updateVoiceToggleIcon(false);
        }
    }

    function stopPopupVoiceInput() {
        if (popupMediaRecorder && isRecording) {
            popupMediaRecorder.stop();
            popupMediaRecorder.stream.getTracks().forEach(track => track.stop());
            logPopup('Stopped recording and released microphone.');
            // Defensive: ensure icon resets if stop is called outside normal flow
            updateVoiceToggleIcon(false);
        }
    }

    function logPopup(message, type = 'info') {
        if (type === 'error') {
            console.error('[Complete][Popup]', message);
        } else {
            console.log('[Complete][Popup]', message);
        }
    }

    function showError(message) {
        const toast = document.createElement('div');
        toast.className = 'toast error';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    }

    function showSuccess(message) {
        const toast = document.createElement('div');
        toast.className = 'toast success';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // --- Event Listeners ---
    statusFilter?.addEventListener('change', () => {
        loadDocumentList();
    });

    searchInput?.addEventListener('input', () => {
        loadDocumentList();
    });

    // Initial load
    loadDocumentList();

    // Remove initial feedback bar on DOMContentLoaded
    if (voiceFeedback) {
        voiceFeedback.textContent = '';
        voiceFeedback.style.display = 'none';
    }

    // Listen for messages from background script
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.type === "VOICE_FEEDBACK" && voiceFeedback && isRecording) {
            voiceFeedback.textContent = request.text;
        }
    });
});