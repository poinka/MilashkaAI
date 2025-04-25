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
        // Register context menu when the extension is installed/updated
        chrome.runtime.onInstalled.addListener(() => {
            console.log('Extension installed or updated: Setting up context menus');
            this.setupContextMenus();
        });
        
        // Also set up context menus on startup to ensure they're always available
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
        // First remove all existing context menus
        chrome.contextMenus.removeAll(() => {
            console.log('Context menus cleared, creating new ones');
            
            // Create the edit menu with a more unique ID
            const menuId = "milashkaAI_edit_" + Date.now();
            
            try {
                chrome.contextMenus.create({
                    id: menuId,
                    title: "Редактировать с Комплитом...",
                    contexts: ["selection"]
                }, () => {
                    // Check for any creation errors
                    const error = chrome.runtime.lastError;
                    if (error) {
                        console.error('Context menu creation error:', error);
                    } else {
                        console.log('Context menu created successfully with ID:', menuId);
                    }
                });
                
                // Store the ID for later reference
                this.editMenuId = menuId;
            } catch (e) {
                console.error('Failed to create context menu:', e);
            }
        });

        // Remove any existing listeners before adding a new one
        if (this._menuClickHandler) {
            chrome.contextMenus.onClicked.removeListener(this._menuClickHandler);
        }
        
        // Create and store reference to the handler
        this._menuClickHandler = (info, tab) => {
            console.log('Context menu clicked:', info.menuItemId, 'with text:', info.selectionText);
            // Match any Milashka edit menu ID
            if (info.menuItemId && info.menuItemId.includes('milashkaAI_edit_') && info.selectionText) {
                chrome.tabs.sendMessage(tab.id, {
                    type: "SHOW_EDIT_UI",
                    selectedText: info.selectionText
                });
            }
        };
        
        // Add the click listener
        chrome.contextMenus.onClicked.addListener(this._menuClickHandler);
    }

    async handleMessage(request, sender, sendResponse) {
        const handlers = {
            GET_COMPLETION: () => this.handleCompletion(request),
            GET_COMPLETION_STREAM: () => this.handleCompletionStream(request),
            READ_NEXT_CHUNK: () => this.handleReadNextChunk(request),
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
            sendResponse({ 
                error: error.message || 'Unknown error',
                stack: error.stack 
            });
        }
    }

    async handleFormatTranscription(request) {
        console.log('[Complete] Formatting transcription:', {
            text_length: request.text?.length,
            text_sample: request.text?.substring(0, 50) + '...',
            language: request.language || 'ru'
        });
        
        const response = await this.fetchAPI('/voice/format', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: request.text,
                language: request.language || 'ru'
            })
        });
        
        console.log('[Complete] Format response:', response);
        return { formatted_text: response.completion }; // Changed from 'response.text' to match the CompletionResponse schema
    }

    async handleCompletion(request) {
        console.log('[Complete] Handling completion request:', {
            text_length: request.current_text?.length,
            text_sample: request.current_text?.substring(Math.max(0, (request.current_text?.length || 0) - 50)),
            language: request.language || 'ru'
        });
        
        try {
            const response = await this.fetchAPI('/completion/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: request.current_text, // Ensure this matches server schema
                    language: request.language || 'ru'
                })
            });
            
            console.log('[Complete] Completion API response:', response);
            // Corrected field name from response.suggestion to response.completion
            return { suggestion: response.completion }; 
        } catch (error) {
            console.error('[Complete] Completion API error:', error);
            throw error;
        }
    }

    async handleCompletionStream(request) {
        try {
            const apiUrl = await this.getApiUrl();
            const url = `${apiUrl}/completion/stream`;
            console.log(`[Complete] Starting streaming completion`);
            
            const controller = new AbortController();
            let timeoutId = null;
            
            // Create an auto-reset timeout
            const resetTimeout = () => {
                if (timeoutId) clearTimeout(timeoutId);
                timeoutId = setTimeout(() => {
                    console.log('[Complete] Stream timeout');
                    controller.abort();
                }, 5000); // 5 second timeout if no tokens received
            };
            
            const response = await fetch(url, {
                method: 'POST',
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive'
                },
                body: JSON.stringify({
                    text: request.current_text,
                    language: request.language || 'ru'
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            // Define the stream object with readNextChunk and cancel
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let fullSuggestion = '';
            let buffer = '';

            const streamObj = {
                readNextChunk: async () => {
                    try {
                        resetTimeout();
                        const { value, done } = await reader.read();
                        if (done) {
                            if (timeoutId) clearTimeout(timeoutId);
                            return { done: true };
                        }
                        const chunk = decoder.decode(value, { stream: true });
                        buffer += chunk;
                        const messages = [];
                        const lines = buffer.split('\n\n');
                        buffer = lines.pop() || '';
                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                const token = line.slice(6);
                                if (token) {
                                    fullSuggestion += token;
                                    messages.push({ token, suggestion: fullSuggestion });
                                }
                            }
                        }
                        return { messages, done: false };
                    } catch (error) {
                        if (timeoutId) clearTimeout(timeoutId);
                        if (error.name === 'AbortError') {
                            console.log('[Complete] Stream aborted');
                            return { done: true };
                        }
                        throw error;
                    }
                },
                cancel: () => {
                    if (timeoutId) clearTimeout(timeoutId);
                    controller.abort();
                    reader.cancel();
                }
            };

            // Register stream in map and return its ID
            if (!this.activeStreams) this.activeStreams = new Map();
            const streamId = `stream-${Date.now()}`;
            this.activeStreams.set(streamId, streamObj);
            console.log(`[Complete] Created stream with ID: ${streamId}`);
            return { id: streamId };
        } catch (error) {
            console.error('[Complete] Stream error:', error);
            throw error;
        }
    }

    // Handler for reading the next chunk from a streaming response
    async handleReadNextChunk(request) {
        console.log('[Complete] READ_NEXT_CHUNK called with request:', { 
            id: request.id,
            hasStream: !!request.stream,
            hasReader: !!request.responseReader
        });
        
        const streamId = request.id;
        if (!streamId) {
            console.error('[Complete] Stream ID missing in READ_NEXT_CHUNK request');
            return { done: true, error: "Stream ID is required" };
        }
        
        // Retrieve the active stream using the ID
        // Since streams are stateful and this is cross-message,
        // we'll store active streams in a map
        if (!this.activeStreams) {
            this.activeStreams = new Map();
            console.log('[Complete] Initialized active streams map');
        }
        
        const stream = this.activeStreams.get(streamId);
        if (!stream) {
            // Create new stream state if first request
            if (request.stream && request.readNextChunk) {
                this.activeStreams.set(streamId, {
                    readNextChunk: request.readNextChunk
                });
                console.log(`[Complete] New stream created with ID: ${streamId}`);
                return { id: streamId, done: false, messages: [] };
            } else {
                console.error('[Complete] Stream not found and no initialization data provided',
                              { streamId, hasStream: !!request.stream, hasReadNextChunk: !!request.readNextChunk });
                return { done: true, error: "Stream not found" };
            }
        }
        
        try {
            // Use the stream's readNextChunk function to get the next chunk
            console.log(`[Complete] Reading next chunk from stream ${streamId}`);
            if (!stream.readNextChunk || typeof stream.readNextChunk !== 'function') {
                console.error(`[Complete] Invalid stream object for ${streamId}, missing readNextChunk function`);
                this.activeStreams.delete(streamId);
                return { done: true, error: "Invalid stream object" };
            }
            
            const result = await stream.readNextChunk();
            
            // Handle null or undefined result
            if (!result) {
                console.error(`[Complete] Stream ${streamId} returned null/undefined result`);
                this.activeStreams.delete(streamId);
                return { done: true, messages: [] };
            }
            
            // If the stream is done, clean up
            if (result.done) {
                this.activeStreams.delete(streamId);
                console.log(`[Complete] Stream ${streamId} completed and cleaned up`);
            }
            
            return result;
        } catch (error) {
            // Clean up on error
            this.activeStreams.delete(streamId);
            console.error(`[Complete] Error reading from stream ${streamId}:`, error);
            return { done: true, error: error.message || "Stream error" };
        }
    }

    async handleUpload(request) {
        if (!Array.isArray(request.fileData)) {
            console.error('Invalid fileData type:', request.fileData, 'Expected Array');
            throw new Error('File data must be an array of bytes');
        }
        const uint8Array = new Uint8Array(request.fileData);
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
        console.log('Handling transcription request with audio type:', request.audioType, 
            'and language:', request.language);
        
        if (!request.audioData || request.audioData.length === 0) {
            throw new Error('No audio data received');
        }
        
        const formData = new FormData();
        
        // Create a Blob from audioData, handling both ArrayBuffer and Uint8Array formats
        let audioBlob;
        if (request.audioData instanceof ArrayBuffer) {
            audioBlob = new Blob([new Uint8Array(request.audioData)], { 
                type: request.audioType || 'audio/webm;codecs=opus'
            });
        } else if (Array.isArray(request.audioData)) {
            // Convert array back to Uint8Array
            audioBlob = new Blob([new Uint8Array(request.audioData)], { 
                type: request.audioType || 'audio/webm;codecs=opus'
            });
        } else {
            audioBlob = new Blob([request.audioData], { 
                type: request.audioType || 'audio/webm;codecs=opus'
            });
        }
        
        if (audioBlob.size === 0) {
            throw new Error('Empty audio recording');
        }
        
        console.log('Audio blob created, size:', audioBlob.size, 'bytes');
        
        // Append with correct field name 'file' as expected by the server
        formData.append('file', audioBlob, 'recording.webm');
        formData.append('language', request.language || 'ru');

        try {
            // Log the exact URL being used for debugging
            const apiUrl = await this.getApiUrl();
            console.log('Base API URL:', apiUrl);
            
            console.log('Sending audio to server for transcription...');
            const response = await this.fetchAPI('/voice/transcribe', {
                method: 'POST', 
                body: formData
            });
            
            console.log('Transcription response:', response);
            if (!response || !response.text) {
                throw new Error('Server returned invalid response format');
            }
            return { transcription: response.text };
        } catch (error) {
            console.error('Transcription error:', error);
            
            // Provide more user-friendly error messages
            let errorMessage = 'Failed to transcribe audio: ';
            if (error.message.includes('exceeded')) {
                errorMessage += 'Audio is too long. Please keep recordings under 60 seconds.';
            } else if (error.message.includes('format')) {
                errorMessage += 'Unsupported audio format. Please try again.';
            } else if (error.message.includes('timeout')) {
                errorMessage += 'Server took too long to respond. Please try again.';
            } else {
                errorMessage += error.message;
            }
            
            throw new Error(errorMessage);
        }
    }

    async handleEdit(request) {
        console.log('[Complete] Handling edit request:', {
            prompt: request.prompt,
            language: request.language,
            textLength: request.selected_text ? request.selected_text.length : 0
        });

        try {
            const apiUrl = await this.getApiUrl();
            console.log('[Complete] Using API URL:', apiUrl);
            
            // Fix for 422 error - use just the endpoint name without leading slash
            // this avoids double-including /api/v1 which is already in the apiUrl
            const response = await this.fetchAPI('/editing', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    selected_text: request.selected_text,
                    prompt: request.prompt,
                    language: request.language || 'ru'
                })
            });

            console.log('[Complete] Edit API response:', response);

            if (!response.edited_text) {
                console.warn('[Complete] Warning: API returned empty edited_text');
            }
            
            return {
                success: true,  // Add this line
                edited_text: response.edited_text,
                confidence: response.confidence,
                alternatives: response.alternatives,
                warning: response.warning
            };
        } catch (error) {
            console.error('[Complete] Error in handleEdit:', error);
            throw error; // Re-throw to be caught by the message handler
        }
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
        try {
            // Handle popup recording (popup doesn't have tabId)
            const isPopup = !tabId || tabId === -1;
            
            console.log(`Starting voice input for ${isPopup ? 'popup' : 'tab ' + tabId}`);
            
            const mediaStream = await navigator.mediaDevices.getUserMedia({ 
                audio: true,
                video: false
            });
            
            console.log('Media stream obtained:', mediaStream.id);
            
            const connection = {
                stream: mediaStream,
                recorder: new MediaRecorder(mediaStream, {
                    mimeType: 'audio/webm'
                })
            };

            const connectionId = isPopup ? 'popup' : tabId;
            this.activeConnections.set(connectionId, connection);
            
            console.log(`Created MediaRecorder for ${connectionId}`, connection.recorder.state);
            
            // Set up data handling
            connection.recorder.ondataavailable = async (event) => {
                console.log(`Got audio data: ${event.data.size} bytes`);
                
                if (event.data.size > 0) {
                    try {
                        console.log('Processing audio chunk for transcription');
                        const response = await this.handleTranscription({
                            audioData: await event.data.arrayBuffer(),
                            audioType: event.data.type
                        });
                        
                        console.log('Transcription result:', response.transcription);
                        
                        // Send transcription back to UI
                        if (isPopup) {
                            // For popup UI
                            chrome.runtime.sendMessage({
                                type: "VOICE_FEEDBACK",
                                text: response.transcription
                            });
                        } else {
                            // For content script in tab
                            chrome.tabs.sendMessage(tabId, {
                                type: "VOICE_FEEDBACK",
                                text: response.transcription
                            });
                        }
                    } catch (error) {
                        console.error("Transcription error:", error);
                    }
                }
            };
            
            // Handle recording errors
            connection.recorder.onerror = (error) => {
                console.error('MediaRecorder error:', error);
            };
            
            // Start recording
            connection.recorder.start(2000); // Send data every 2 seconds
            console.log('MediaRecorder started:', connection.recorder.state);
            
            return { success: true };
        } catch (error) {
            console.error('Failed to start voice recording:', error);
            return { error: error.message || "Failed to access microphone" };
        }
    }

    async handleTrackSuggestion(request) {
        try {
            await this.fetchAPI('/feedback/track-suggestion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    suggestion_text: request.suggestion_text,
                    document_context: request.document_context,
                    was_accepted: request.was_accepted,
                    source: request.source || 'completion',
                    language: request.language || 'ru'
                })
            });
            return { success: true };
        } catch (error) {
            console.error('Failed to track suggestion:', error);
            return { success: false, error: error.message };
        }
    }

    handleStopVoice(tabId) {
        // Handle both popup and tab recording sessions
        const connectionId = !tabId || tabId === -1 ? 'popup' : tabId;
        console.log(`Stopping voice input for ${connectionId}`);
        
        const connection = this.activeConnections.get(connectionId);
        if (connection) {
            try {
                console.log('Stopping MediaRecorder');
                connection.recorder.stop();
                console.log('Stopping media tracks');
                connection.stream.getTracks().forEach(track => track.stop());
                this.activeConnections.delete(connectionId);
                console.log('Recording stopped and resources cleaned up');
            } catch (error) {
                console.error('Error stopping voice recording:', error);
                return { success: false, error: error.message };
            }
        } else {
            console.warn(`No active connection found for ${connectionId}`);
        }
        
        return { success: true };
    }

    async fetchAPI(endpoint, options = {}) {
        try {
            const apiUrl = await this.getApiUrl();
            // Ensure we don't get double slashes by trimming any trailing slash from apiUrl
            // and ensuring endpoint starts with a slash
            const cleanApiUrl = apiUrl.replace(/\/+$/, '');
            const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
            const url = `${cleanApiUrl}${cleanEndpoint}`;
            
            // Log more details about the request payload for debugging
            if (endpoint.includes('completion')) {
                console.log(`Fetching from ${url}`);
                if (options.body) {
                    try {
                        const bodyData = JSON.parse(options.body);
                        console.log('Request payload:', {
                            current_text_length: bodyData.current_text?.length,
                            current_text_sample: bodyData.current_text?.substring(Math.max(0, (bodyData.current_text?.length || 0) - 50)),
                            has_full_context: !!bodyData.full_document_context,
                            language: bodyData.language
                        });
                    } catch (e) {
                        console.log('Request body (non-JSON):', options.body);
                    }
                }
            } else {
                console.log(`Fetching from ${url}`);
            }
            
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
                    console.error(`API Error: ${errorData.detail || 'Request failed'} (${response.status})`);
                    throw new Error(errorData.detail || `Request failed with status ${response.status}`);
                } catch (jsonError) {
                    // If JSON parsing fails, provide more detailed error based on status code
                    let errorMessage = `Request failed: `;
                    switch(response.status) {
                        case 404:
                            errorMessage += `API endpoint not found. Please check the server is running and the endpoint path is correct.`;
                            break;
                        case 500:
                            errorMessage += `Internal server error. Please try again later.`;
                            break;
                        default:
                            errorMessage += `Status ${response.status} ${response.statusText}`;
                    }
                    throw new Error(errorMessage);
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
