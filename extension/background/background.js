// Background service worker with task queue and error recovery
class TaskQueue {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
        this.retryDelays = [1000, 3000, 5000]; // Retry delays in ms
    }

    async add(task) {
        this.queue.push(task);
        if (!this.isProcessing) {
            await this.process();
        }
    }

    async process() {
        if (this.isProcessing || this.queue.length === 0) return;

        this.isProcessing = true;
        const task = this.queue[0];

        try {
            await this.executeWithRetry(task);
            this.queue.shift(); // Remove completed task
        } catch (error) {
            console.error(`Task failed after all retries:`, error);
            // Move failed task to the end or remove it
            this.queue.shift();
            // Could add to a failed tasks list for later recovery
        } finally {
            this.isProcessing = false;
            if (this.queue.length > 0) {
                await this.process(); // Process next task
            }
        }
    }

    async executeWithRetry(task, attempt = 0) {
        try {
            return await task();
        } catch (error) {
            if (attempt < this.retryDelays.length) {
                await new Promise(resolve => 
                    setTimeout(resolve, this.retryDelays[attempt])
                );
                return this.executeWithRetry(task, attempt + 1);
            }
            throw error; // No more retries
        }
    }
}

class BackgroundService {
    constructor() {
        this.taskQueue = new TaskQueue();
        this.activeConnections = new Map();
        this.setupAPI();
        this.setupContextMenus();
    }

    setupAPI() {
        chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
            // Return true to indicate async response
            this.handleMessage(request, sender, sendResponse);
            return true;
        });
    }

    setupContextMenus() {
        chrome.contextMenus.removeAll(() => {
            chrome.contextMenus.create({
                id: "milashkaEdit",
                title: "Edit with MilashkaAI...",
                contexts: ["selection"]
            });
        });

        chrome.contextMenus.onClicked.addListener((info, tab) => {
            if (info.menuItemId === "milashkaEdit" && info.selectionText) {
                chrome.tabs.sendMessage(tab.id, {
                    type: "SHOW_EDIT_UI",
                    selectedText: info.selectionText
                });
            }
        });
    }

    async handleMessage(request, sender, sendResponse) {
        const handlers = {
            GET_COMPLETION: () => this.handleCompletion(request),
            UPLOAD_DOCUMENT: () => this.handleUpload(request),
            TRANSCRIBE_AUDIO: () => this.handleTranscription(request),
            EDIT_TEXT: () => this.handleEdit(request),
            LIST_DOCUMENTS: () => this.handleListDocuments(),
            DELETE_DOCUMENT: () => this.handleDeleteDocument(request),
            START_VOICE_INPUT: () => this.handleStartVoice(sender.tab?.id),
            STOP_VOICE_INPUT: () => this.handleStopVoice(sender.tab?.id)
        };

        const handler = handlers[request.type];
        if (!handler) {
            sendResponse({ success: false, error: "Unknown request type" });
            return;
        }

        try {
            const result = await this.taskQueue.add(() => handler());
            sendResponse({ success: true, ...result });
        } catch (error) {
            console.error(`Error handling ${request.type}:`, error);
            sendResponse({
                success: false,
                error: error.message || "Operation failed"
            });
        }
    }

    async handleCompletion(request) {
        const response = await this.fetchAPI('/completion/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                current_text: request.current_text,
                full_document_context: request.full_document_context,
                language: request.language || 'ru'
            })
        });
        return { suggestion: response.suggestion };
    }

    async handleUpload(request) {
        const formData = new FormData();
        const blob = new Blob([request.fileData], { type: request.filetype });
        formData.append('file', blob, request.filename);

        const response = await this.fetchAPI('/documents/upload', {
            method: 'POST',
            body: formData
        });
        return { metadata: response };
    }

    async handleTranscription(request) {
        const formData = new FormData();
        const blob = new Blob([request.audioData], { type: request.audioType || 'audio/webm' });
        formData.append('audio_file', blob);
        formData.append('language', request.language || 'ru');

        const response = await this.fetchAPI('/voice/transcribe', {
            method: 'POST',
            body: formData
        });
        return { transcription: response.text };
    }

    async handleEdit(request) {
        const response = await this.fetchAPI('/editing/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selected_text: request.selected_text,
                prompt: request.prompt,
                language: request.language || 'ru'
            })
        });
        return {
            edited_text: response.edited_text,
            confidence: response.confidence,
            alternatives: response.alternatives,
            warning: response.warning
        };
    }

    async handleListDocuments() {
        const response = await this.fetchAPI('/documents/', {
            method: 'GET'
        });
        return { documents: response };
    }

    async handleDeleteDocument(request) {
        const response = await this.fetchAPI(`/documents/${request.doc_id}`, {
            method: 'DELETE'
        });
        return { status: response.status };
    }

    async handleStartVoice(tabId) {
        if (!tabId) return { error: "No active tab" };
        
        const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const connection = {
            stream: mediaStream,
            recorder: new MediaRecorder(mediaStream)
        };

        this.activeConnections.set(tabId, connection);
        
        connection.recorder.ondataavailable = async (event) => {
            if (event.data.size > 0) {
                try {
                    const response = await this.handleTranscription({
                        audioData: await event.data.arrayBuffer(),
                        audioType: event.data.type
                    });
                    
                    chrome.tabs.sendMessage(tabId, {
                        type: "VOICE_FEEDBACK",
                        text: response.transcription
                    });
                } catch (error) {
                    console.error("Transcription error:", error);
                }
            }
        };

        connection.recorder.start(1000); // Capture in 1-second chunks
        return { success: true };
    }

    handleStopVoice(tabId) {
        if (!tabId) return { error: "No active tab" };
        
        const connection = this.activeConnections.get(tabId);
        if (connection) {
            connection.recorder.stop();
            connection.stream.getTracks().forEach(track => track.stop());
            this.activeConnections.delete(tabId);
        }
        return { success: true };
    }

    async fetchAPI(endpoint, options = {}) {
        const apiUrl = await this.getApiUrl();
        const url = `${apiUrl}${endpoint}`;
        
        const response = await fetch(url, {
            ...options,
            headers: {
                ...options.headers,
                'X-Client-Version': chrome.runtime.getManifest().version
            }
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || 'API request failed');
        }

        return response.json();
    }

    async getApiUrl() {
        return new Promise((resolve) => {
            chrome.storage.sync.get(['apiUrl'], (result) => {
                resolve(result.apiUrl || 'http://localhost:8000/api/v1');
            });
        });
    }
}

// Initialize the background service
const backgroundService = new BackgroundService();
console.log("MilashkaAI background service initialized.");
