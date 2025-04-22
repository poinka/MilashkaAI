document.addEventListener('DOMContentLoaded', () => {
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
            showError('No valid files selected. Supported formats: PDF, DOCX, TXT, MD');
            return;
        }

        selectedFiles = new Set(validFiles);
        updateUploadButton();
        showFileList();
    }

    function updateUploadButton() {
        uploadButton.disabled = selectedFiles.size === 0;
        uploadButton.textContent = `Upload ${selectedFiles.size} File${selectedFiles.size !== 1 ? 's' : ''}`;
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
            
            showSuccess('All files uploaded successfully');
            selectedFiles.clear();
            updateUploadButton();
            showFileList();
            loadDocumentList();
            
        } catch (error) {
            showError('Upload failed: ' + error.message);
        } finally {
            isUploading = false;
            progressContainer.style.display = 'none';
        }
    });

    async function uploadFile(file) {
        const reader = new FileReader();
        
        return new Promise((resolve, reject) => {
            reader.onload = async (e) => {
                try {
                    const response = await chrome.runtime.sendMessage({
                        type: "UPLOAD_DOCUMENT",
                        filename: file.name,
                        filetype: file.type,
                        fileData: e.target.result
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

            reader.onerror = () => reject(new Error('File reading failed'));
            reader.readAsArrayBuffer(file);
        });
    }

    function updateProgress(percent) {
        progressBar.style.width = `${percent}%`;
        progressText.textContent = `${Math.round(percent)}%`;
    }

    // --- Document List Handling ---
    async function loadDocumentList() {
        if (!docList) return;
    
        try {
            const response = await chrome.runtime.sendMessage({ type: "LIST_DOCUMENTS" });
            
            console.log('LIST_DOCUMENTS response:', response); // Debug log
    
            if (response === undefined || response === null) {
                showError('Failed to load documents: No response from background script');
                console.error('No response received from background script');
                docList.innerHTML = '<li class="no-documents">Error loading documents</li>';
                return;
            }
    
            if (response.success && Array.isArray(response.documents)) {
                renderDocumentList(response.documents);
            } else {
                const errorMsg = response.error || 
                    (!response.success ? 'Request failed' : 
                    'Missing or invalid documents array');
                showError(`Failed to load documents: ${errorMsg}`);
                console.error('Invalid response:', response);
                docList.innerHTML = '<li class="no-documents">Failed to load documents</li>';
            }
        } catch (error) {
            showError('Error loading documents: ' + error.message);
            console.error('Load documents error:', error);
            docList.innerHTML = '<li class="no-documents">Error loading documents</li>';
        }
    }

    function renderDocumentList(documents) {
        if (!Array.isArray(documents)) {
            console.error('Invalid documents data:', documents);
            docList.innerHTML = '<li class="no-documents">Error loading documents</li>';
            return;
        }
    
        const filteredDocs = filterDocuments(documents);
        docList.innerHTML = '';
    
        if (filteredDocs.length === 0) {
            docList.innerHTML = '<li class="no-documents">No documents found</li>';
            return;
        }
    
        filteredDocs.forEach(doc => {
            const li = document.createElement('li');
            li.innerHTML = `
                <div class="doc-info">
                    <span class="doc-name">${doc.filename}</span>
                    <span class="status-badge status-${doc.status}">${doc.status}</span>
                </div>
                <button class="delete-doc" data-id="${doc.doc_id}">&times;</button>
            `;
            docList.appendChild(li);
        });

        // Add delete handlers
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
                        loadDocumentList(); // Refresh list on success
                    } else {
                        showError('Failed to delete document: ' + response.error);
                    }
                } catch (error) {
                    console.error(`Error deleting document:`, error);
                    showError('Error deleting document: ' + error.message);
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
    voiceToggle?.addEventListener('click', toggleVoiceInput);

    function toggleVoiceInput() {
        if (isRecording) {
            stopVoiceInput();
        } else {
            startVoiceInput();
        }
    }

    function startVoiceInput() {
        chrome.runtime.sendMessage({ type: "START_VOICE_INPUT" }, (response) => {
            if (response.success) {
                isRecording = true;
                voiceToggle.classList.add('recording');
                voiceToggle.querySelector('.voice-status').textContent = 'Stop Recording';
                voiceFeedback.style.display = 'block';
                voiceFeedback.textContent = 'Listening...';
            } else {
                showError('Failed to start voice input: ' + response.error);
            }
        });
    }

    function stopVoiceInput() {
        chrome.runtime.sendMessage({ type: "STOP_VOICE_INPUT" }, (response) => {
            isRecording = false;
            voiceToggle.classList.remove('recording');
            voiceToggle.querySelector('.voice-status').textContent = 'Start Voice Input';
            voiceFeedback.style.display = 'none';
        });
    }

    // --- UI Feedback ---
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

    // Listen for messages from background script
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.type === "VOICE_FEEDBACK") {
            if (voiceFeedback && isRecording) {
                voiceFeedback.textContent = request.text;
            }
        }
    });
});