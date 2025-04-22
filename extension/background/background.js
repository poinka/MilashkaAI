class TaskQueue {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
        this.retryDelays = [1000, 3000, 5000];
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
            this.queue.shift();
        } catch (error) {
            console.error(`Task failed after all retries:`, error);
            this.queue.shift();
        } finally {
            this.isProcessing = false;
            if (this.queue.length > 0) {
                await this.process();
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
            throw error;
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
            console.log('Received message:', request);
            if (request.type === "LIST_DOCUMENTS") {
                console.log('Directly handling LIST_DOCUMENTS');
                this.handleListDocuments()
                    .then(result => {
                        console.log('Sending LIST_DOCUMENTS response:', result);
                        sendResponse(result);
                    })
                    .catch(error => {
                        console.error('LIST_DOCUMENTS error:', error);
                        sendResponse({ success: false, error: error.message });
                    });
            } else {
                this.handleMessage(request, sender, sendResponse);
            }
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
            GET_COMPLETION_STREAM: () => this.handleCompletionStream(request),
            UPLOAD_DOCUMENT: () => this.handleUpload(request),
            TRANSCRIBE_AUDIO: () => this.handleTranscription(request),
            EDIT_TEXT: () => this.handleEdit(request),
            DELETE_DOCUMENT: () => this.handleDeleteDocument(request),
            START_VOICE_INPUT: () => this.handleStartVoice(sender.tab?.id),
            STOP_VOICE_INPUT: () => this.handleStopVoice(sender.tab?.id),
            TRACK_SUGGESTION: () => this.handleTrackSuggestion(request),
            FORMAT_TRANSCRIPTION: () => this.handleFormatTranscription(request)
        };

        const handler = handlers[request.type];
        if (!handler) {
            console.error(`Unknown request type: ${request.type}`);
            sendResponse({ success: false, error: "Unknown request type" });
            return;
        }

        try {
            console.log(`Processing ${request.type}`);
            // Execute handler directly and get its result
            const result = await handler();
            console.log(`Result for ${request.type}:`, result);
            // For streaming completions, don't overwrite the stream property
            if (request.type === 'GET_COMPLETION_STREAM') {
                sendResponse({ success: true, ...result });
            } else {
                sendResponse({ success: true, ...result });
            }
        } catch (error) {
            console.error(`Error handling ${request.type}:`, error);
            sendResponse({ success: false, error: error.message || "Operation failed" });
        }
    }

    async handleFormatTranscription(request) {
        const response = await this.fetchAPI('/voice/format', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: request.text,
                language: request.language || 'ru'
            })
        });
        return { formatted_text: response.text };
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

    async handleCompletionStream(request) {
        try {
            const apiUrl = await this.getApiUrl();
            const url = `${apiUrl}/completion/stream`;
            
            console.log(`Starting streaming completion from ${url}`);
            
            // Initialize SSE connection
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 60000);
            
            const response = await fetch(url, {
                method: 'POST',
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    'X-Client-Version': chrome.runtime.getManifest().version
                },
                body: JSON.stringify({
                    current_text: request.current_text,
                    full_document_context: request.full_document_context,
                    language: request.language || 'ru'
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Setup streaming
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullSuggestion = '';
            let buffer = '';
            
            return {
                stream: true,
                responseReader: reader,
                readNextChunk: async () => {
                    try {
                        const { value, done } = await reader.read();
                        
                        if (done) {
                            clearTimeout(timeoutId);
                            return { done: true };
                        }
                        
                        const chunk = decoder.decode(value, { stream: true });
                        buffer += chunk;
                        
                        // Process complete SSE messages
                        const messages = [];
                        const lines = buffer.split('\n\n');
                        
                        // Process all complete messages
                        buffer = lines.pop() || ''; // Keep the last incomplete part in buffer
                        
                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                try {
                                    const data = JSON.parse(line.substring(6));
                                    if (data.token) {
                                        fullSuggestion += data.token;
                                        messages.push({
                                            token: data.token,
                                            suggestion: fullSuggestion
                                        });
                                    }
                                    if (data.done) {
                                        messages.push({ done: true });
                                    }
                                } catch (e) {
                                    console.error('Error parsing SSE data:', e);
                                }
                            }
                        }
                        
                        return { messages, done: false };
                    } catch (error) {
                        clearTimeout(timeoutId);
                        reader.cancel();
                        throw error;
                    }
                },
                cancel: () => {
                    clearTimeout(timeoutId);
                    reader.cancel();
                }
            };
        } catch (error) {
            console.error('Streaming completion error:', error);
            throw error;
        }
    }

    async handleUpload(request) {
        if (!Array.isArray(request.fileData)) {
            console.error('Invalid fileData type:', request.fileData, 'Expected Array');
            throw new Error('File data must be an array of bytes');
        }
        const uint8Array = new Uint8Array(request.fileData);
        console.log('Received fileData sample:', uint8Array.slice(0, 10));
        console.log('Filename:', request.filename, 'Filetype:', request.filetype);
        const formData = new FormData();
        const blob = new Blob([uint8Array], { type: request.filetype });
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
        console.log('Fetching document list from API');
        try {
            // fetchAPI returns the list directly based on the server response
            const documentsList = await this.fetchAPI('/documents/', {
                method: 'GET'
            });
            console.log('Raw server response (list):', documentsList);
            
            // Validate if the response is actually an array
            if (!Array.isArray(documentsList)) {
                // Log the unexpected response for debugging
                console.error('Invalid response format: expected an array, received:', documentsList);
                throw new Error('Invalid response format: expected an array of documents');
            }
            
            console.log('Processed documents:', documentsList);
            
            // Return the expected structure
            return {
                success: true,
                documents: documentsList
            };
        } catch (error) {
            console.error('Failed to fetch documents:', error);
            // Return the error structure expected by the caller
            return {
                success: false, 
                documents: [],
                message: error.message || "Failed to fetch documents"
            };
        }
    }

    async handleDeleteDocument(request) {
        try {
            const response = await this.fetchAPI(`/documents/${request.doc_id}`, {
                method: 'DELETE'
            });
            // Check if the server responded with a success status (e.g., 204 No Content)
            // fetchAPI throws an error for non-ok statuses, so if we get here, it was likely successful.
            // We rely on fetchAPI to have handled non-2xx responses.
            return { success: true }; 
        } catch (error) {
            console.error(`Failed to delete document ${request.doc_id}:`, error);
            return { success: false, error: error.message || "Failed to delete document" };
        }
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

        connection.recorder.start(1000);
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
        try {
            const apiUrl = await this.getApiUrl();
            const url = `${apiUrl}${endpoint}`;
            console.log(`Fetching from ${url}`);
            
            // Set timeout and implement retry mechanism for network errors
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 60000); // Increased to 60 seconds for LLM inference
            
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    ...options.headers,
                    'X-Client-Version': chrome.runtime.getManifest().version
                }
            }).finally(() => {
                clearTimeout(timeoutId);
            });
            
            console.log(`Response status: ${response.status} ${response.statusText}`);
            if (!response.ok) {
                try {
                    // Try to parse error as JSON
                    const errorData = await response.json();
                    console.error(`Fetch error: ${errorData.detail || 'API request failed'}`);
                    throw new Error(errorData.detail || 'API request failed');
                } catch (jsonError) {
                    // If JSON parsing fails, use status text
                    throw new Error(`HTTP error! status: ${response.status} ${response.statusText}`);
                }
            }
            
            // For 204 No Content responses, just return an empty object
            if (response.status === 204) {
                console.log('Empty response (204 No Content) - returning empty object');
                return {};
            }

            // For other successful responses, parse as JSON
            const json = await response.json();
            console.log(`API Response:`, json);
            return json;
        } catch (error) {
            // More detailed error logging and handling
            if (error.name === 'AbortError') {
                console.error(`API request timed out: ${endpoint}`);
                throw new Error(`Request timed out. Please try again or check your network connection.`);
            } else if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
                console.error(`Network error when connecting to API: ${error.message}`);
                throw new Error(`Connection failed. Please make sure the server is running and you have an internet connection.`);
            } else {
                console.error(`API Error:`, error);
                throw new Error(`API request failed: ${error.message}`);
            }
        }
    }
    
    async getApiUrl() {
        return new Promise((resolve) => {
            chrome.storage.sync.get(['apiUrl'], (result) => {
                const url = result.apiUrl || 'http://localhost:8000/api/v1';
                console.log('Resolved API URL:', url);
                resolve(url);
            });
        });
    }
}

const backgroundService = new BackgroundService();
console.log("MilashkaAI background service initialized.")