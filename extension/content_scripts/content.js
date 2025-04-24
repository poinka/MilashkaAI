console.log("MilashkaAI content script loaded.");

// default API URL in case storage hasn't loaded yet
window.MILASHKA_API_URL = 'http://localhost:8000/api/v1';

function showContextInvalidatedError() {
    // Remove any existing error notification first
    const existing = document.getElementById('milashka-context-error');
    if (existing) existing.remove();
    
    const errorBar = document.createElement('div');
    errorBar.id = 'milashka-context-error';
    Object.assign(errorBar.style, {
        position: 'fixed',
        top: '0',
        left: '0',
        right: '0',
        backgroundColor: '#f44336',
        color: 'white',
        padding: '12px',
        textAlign: 'center',
        zIndex: '999999',
        cursor: 'pointer',
        fontFamily: 'system-ui'
    });
    
    errorBar.textContent = 'Extension needs to be reloaded. Click here to refresh the page';
    errorBar.onclick = () => window.location.reload();
    document.body.appendChild(errorBar);
}

class SuggestionManager {
    constructor() {
        this.currentSuggestion = null;
        this.suggestionElement = null;
        this.activeInputElement = null;
        this.debounceTimer = null;
        this.DEBOUNCE_DELAY = 1000;  // Longer debounce to avoid too many requests
        this.lastUpdate = 0;
        this.updateThrottle = 10;    // Faster UI updates for smoother token display
        this.abortController = null;
        this.currentRequestId = 0;
        this.streamInProgress = false;
        this.justCanceledByKeystroke = false;  // Flag to prevent immediate restart
        this.lastKeystrokeTime = 0;            // Track when user last typed
        // Bind methods to ensure correct 'this' context
        this.displaySuggestion = this.displaySuggestion.bind(this);
        this.cancelStream = this.cancelStream.bind(this);
    }

    showToast(message, type = 'info') {
        // Notification functionality removed - only log to console
        console.log(`[MilashkaAI Toast] ${type}: ${message}`);
        // No UI elements created or shown
    }

    cancelStream(source = 'unknown') {
        console.log(`[MilashkaAI] cancelStream called from: ${source}`);
        if (this.abortController) {
            // Save the stack trace before aborting
            const stackTrace = new Error().stack;
            console.log('[MilashkaAI] Abort controller stack:', stackTrace);
            
            this.abortController.abort();
            this.abortController = null;
            console.log(`[MilashkaAI] Completion cancelled from: ${source}`);
        }
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = null;
        }
        this.currentRequestId++;
        this.streamInProgress = false;
        
        // If cancellation is due to keystroke, mark it to prevent immediate restart
        if (source === 'globalKeydown' || source === 'handleInput_newInput') {
            this.justCanceledByKeystroke = true;
            this.lastKeystrokeTime = Date.now();
            
            // Auto-reset after a delay
            setTimeout(() => {
                this.justCanceledByKeystroke = false;
            }, 1500);
        }
        
        this.clearSuggestion();
    }

    ensureOverlay(element) {
        // Only wrap once
        if (element.parentNode && element.parentNode.classList && element.parentNode.classList.contains('milashka-input-wrapper')) {
            console.log('[MilashkaAI] ensureOverlay: already wrapped');
            return element.parentNode;
        }
        // Remove any old wrapper (if present)
        if (element.parentNode && element.parentNode.classList && element.parentNode.classList.contains('milashka-old-wrapper')) {
            const oldWrapper = element.parentNode;
            oldWrapper.parentNode.insertBefore(element, oldWrapper);
            oldWrapper.remove();
        }
        // Create wrapper
        try {
            const wrapper = document.createElement('div');
            wrapper.className = 'milashka-input-wrapper';
            wrapper.style.position = 'relative';
            wrapper.style.display = 'inline-block';
            wrapper.style.width = element.offsetWidth + 'px';
            wrapper.style.height = element.offsetHeight + 'px';
            element.parentNode.insertBefore(wrapper, element);
            wrapper.appendChild(element);
            console.log('[MilashkaAI] ensureOverlay: wrapper created');
            return wrapper;
        } catch (e) {
            console.error('[MilashkaAI] ensureOverlay: failed to create overlay', e);
            return null;
        }
    }

    displaySuggestion(element, suggestionText) {
        console.log('[MilashkaAI] displaySuggestion called', { element, suggestionText });
        // Throttle updates
        const now = Date.now();
        if (now - this.lastUpdate < this.updateThrottle) return;
        this.lastUpdate = now;

        if (!suggestionText) {
            this.clearSuggestion();
            return;
        }
        this.clearSuggestion();
        this.currentSuggestion = suggestionText;
        this.activeInputElement = element;
        const wrapper = this.ensureOverlay(element);
        if (!wrapper) {
            console.error('[MilashkaAI] displaySuggestion: could not get wrapper for element', element);
            return;
        }
        // Remove any old overlays
        const oldOverlays = wrapper.querySelectorAll('.milashka-suggestion-overlay');
        oldOverlays.forEach(node => node.remove());
        // Create overlay if needed
        this.suggestionElement = document.createElement('div');
        this.suggestionElement.className = 'milashka-suggestion-overlay';
        // Style to match input
        const style = window.getComputedStyle(element);
        Object.assign(this.suggestionElement.style, {
            position: 'absolute',
            left: style.paddingLeft,
            top: style.paddingTop,
            color: '#999',
            pointerEvents: 'none',
            font: style.font,
            whiteSpace: 'pre-wrap',
            opacity: 0.7,
            zIndex: 10,
            width: '100%',
            height: '100%',
            overflow: 'hidden',
        });
        // Show only the part after the user's input
        const value = element.value;
        let caretPos = element.selectionStart;
        let before = value.substring(0, caretPos);
        let after = suggestionText.substring(caretPos);
        // Render ghost text after caret
        this.suggestionElement.innerHTML =
            `<span style="visibility:hidden">${this.escapeHtml(before)}</span><span>${this.escapeHtml(after)}</span>`;
        wrapper.appendChild(this.suggestionElement);
        console.log('[MilashkaAI] displaySuggestion: overlay appended');
    }

    escapeHtml(str) {
        return str.replace(/[&<>"']/g, function(tag) {
            const charsToReplace = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            };
            return charsToReplace[tag] || tag;
        });
    }

    clearSuggestion() {
        if (this.suggestionElement && this.suggestionElement.parentNode) {
            this.suggestionElement.parentNode.removeChild(this.suggestionElement);
            this.suggestionElement = null;
        }
        this.currentSuggestion = null;
        this.activeInputElement = null;
    }

    insertText(element, text) {
        if (!element || !text) return;
        
        if (element.isContentEditable) {
            // For contentEditable elements
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                range.deleteContents();
                range.insertNode(document.createTextNode(text));
                selection.collapseToEnd();
            }
        } else {
            // For input and textarea elements
            const start = element.selectionStart || 0;
            const end = element.selectionEnd || 0;
            const originalText = element.value || '';
            
            element.value = originalText.substring(0, start) + text + originalText.substring(end);
            
            // Set cursor position after the inserted text
            element.selectionStart = element.selectionEnd = start + text.length;
            
            // Trigger input event to notify any listeners
            element.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }

    acceptSuggestion() {
        if (this.currentSuggestion && this.activeInputElement) {
            this.insertText(this.activeInputElement, this.currentSuggestion);
            this.trackSuggestionFeedback(true);
            this.clearSuggestion();
            // After accepting, allow new completions
            this.cancelStream('acceptSuggestion');
            return true;
        }
        return false;
    }

    trackSuggestionFeedback(wasAccepted) {
        if (!this.currentSuggestion) return;
        
        chrome.runtime.sendMessage({
            type: "TRACK_SUGGESTION",
            suggestion_text: this.currentSuggestion,
            document_context: this.getContext(),
            was_accepted: wasAccepted,
            source: "completion",
            language: document.documentElement.lang || 'ru'
        }).catch(err => {
            console.error("Failed to track suggestion feedback:", err);
            if (err.message.includes('Extension context invalidated')) {
                showContextInvalidatedError();
            }
        });
    }

    getContext() {
        if (!this.activeInputElement || !this.activeInputElement.value) return '';
        const start = Math.max(0, this.activeInputElement.selectionStart - 200);
        const end = Math.min(this.activeInputElement.value.length, this.activeInputElement.selectionStart + 200);
        return this.activeInputElement.value.substring(start, end);
    }
}

class EditingUI {
    constructor() {
        this.floatingMenu = null;
        this.currentSelection = null;
        this.currentSelectionRange = null;
        this.isProcessing = false;
    }

    showFloatingMenu(x, y, selectedText) {
        this.hideFloatingMenu();
        this.currentSelection = selectedText;

        this.floatingMenu = document.createElement('div');
        this.floatingMenu.className = 'milashka-floating-menu';
        Object.assign(this.floatingMenu.style, {
            position: 'fixed',
            left: `${x}px`,
            top: `${y}px`,
            backgroundColor: 'white',
            borderRadius: '4px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            padding: '8px',
            zIndex: '1000000'
        });

        const inputWrapper = document.createElement('div');
        inputWrapper.style.display = 'flex';
        inputWrapper.style.marginBottom = '8px';

        const input = document.createElement('input');
        Object.assign(input.style, {
            width: '200px',
            padding: '6px',
            marginRight: '4px',
            border: '1px solid #ddd',
            borderRadius: '4px'
        });
        input.placeholder = 'Describe edit (or use voice)';

        const voiceButton = document.createElement('button');
        Object.assign(voiceButton.style, {
            padding: '6px 12px',
            backgroundColor: '#4CAF50',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
        });
        voiceButton.innerHTML = '🎙️';
        voiceButton.onclick = () => this.startVoiceEdit();

        inputWrapper.appendChild(input);
        inputWrapper.appendChild(voiceButton);

        const buttonsWrapper = document.createElement('div');
        buttonsWrapper.style.display = 'flex';
        buttonsWrapper.style.gap = '8px';

        const submitButton = document.createElement('button');
        Object.assign(submitButton.style, {
            padding: '6px 12px',
            backgroundColor: '#4CAF50',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            flex: '1'
        });
        submitButton.textContent = 'Edit';

        const cancelButton = document.createElement('button');
        Object.assign(cancelButton.style, {
            padding: '6px 12px',
            backgroundColor: '#f44336',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer'
        });
        cancelButton.textContent = 'Cancel';

buttonsWrapper.appendChild(submitButton);
        buttonsWrapper.appendChild(cancelButton);

this.floatingMenu.appendChild(inputWrapper);
        this.floatingMenu.appendChild(buttonsWrapper);

        submitButton.onclick = () => {
            if (!this.isProcessing && input.value) {
                this.performEdit(this.currentSelection, input.value);
            }
        };

        cancelButton.onclick = () => this.hideFloatingMenu();

        input.onkeydown = (e) => {
            if (e.key === 'Enter' && !this.isProcessing && input.value) {
                this.performEdit(this.currentSelection, input.value);
            } else if (e.key === 'Escape') {
                this.hideFloatingMenu();
            }
        };

        document.body.appendChild(this.floatingMenu);
        input.focus();

        document.addEventListener('mousedown', this.handleClickOutsideMenu);
    }

    hideFloatingMenu() {
        if (this.floatingMenu) {
            this.floatingMenu.remove();
            this.floatingMenu = null;
            this.currentSelection = null;
            this.currentSelectionRange = null;
            document.removeEventListener('mousedown', this.handleClickOutsideMenu);
        }
    }

    handleClickOutsideMenu = (event) => {
        if (this.floatingMenu && !this.floatingMenu.contains(event.target)) {
            this.hideFloatingMenu();
        }
    }

    async performEdit(selectedText, prompt) {
        if (this.isProcessing) return;

        this.isProcessing = true;
        this.updateMenuState(true, 'Processing...');
        
        console.log('[MilashkaAI] Starting edit with prompt:', prompt);

        try {
            console.log('[MilashkaAI] Sending edit request to background script');
            const response = await chrome.runtime.sendMessage({
                type: "EDIT_TEXT",
                selected_text: selectedText,
                prompt: prompt,
                language: document.documentElement.lang || 'ru'
            });

            console.log('[MilashkaAI] Received edit response:', response);

            if (response.success) {
                console.log('[MilashkaAI] Edit successful, applying edit:', response.edited_text);
                this.applyEdit(response.edited_text, response.confidence);
                if (response.warning) {
                    this.showFeedback(response.warning, 'warning');
                }
            } else {
                console.error('[MilashkaAI] Edit failed:', response.error);
                throw new Error(response.error || 'Unknown error occurred');
            }
        } catch (error) {
            console.error('[MilashkaAI] Edit error:', error);
            this.showFeedback(`Edit failed: ${error.message}`, 'error');
        } finally {
            this.isProcessing = false;
            this.hideFloatingMenu();
        }
    }

    applyEdit(editedText, confidence) {
        try {
            const selection = window.getSelection();
            
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                
                // Delete the current selection contents
                range.deleteContents();
                
                // Create a proper text node for the edited content
                if (editedText) {
                    // Check if the edited text contains HTML
                    if (/<[a-z][\s\S]*>/i.test(editedText)) {
                        // For HTML content
                        const temp = document.createElement('div');
                        temp.innerHTML = editedText;
                        
                        // Insert each child node from the temp div
                        const fragment = document.createDocumentFragment();
                        while (temp.firstChild) {
                            fragment.appendChild(temp.firstChild);
                        }
                        range.insertNode(fragment);
                    } else {
                        // For plain text content
                        const textNode = document.createTextNode(editedText);
                        range.insertNode(textNode);
                    }
                    
                    // Collapse the selection to the end of the inserted content
                    selection.collapseToEnd();
                    
                    // Show confidence feedback if needed
                    if (confidence < 0.7) {
                        this.showFeedback(
                            'Low confidence in edit. Please review the changes.',
                            'warning'
                        );
                    } else {
                        this.showFeedback('Edit applied successfully', 'info');
                    }
                } else {
                    this.showFeedback('No edit content received', 'error');
                }
            } else {
                this.showFeedback('Could not apply edit: no active selection', 'error');
            }
        } catch (error) {
            console.error('Error applying edit:', error);
            this.showFeedback(`Failed to apply edit: ${error.message}`, 'error');
        }
    }

    updateMenuState(isProcessing, message = '') {
        if (!this.floatingMenu) return;

        const input = this.floatingMenu.querySelector('input');
        const submitButton = this.floatingMenu.querySelector('button:not([class*="voice"])');

        if (isProcessing) {
            input.disabled = true;
            submitButton.disabled = true;
            submitButton.textContent = message;
        } else {
            input.disabled = false;
            submitButton.disabled = false;
            submitButton.textContent = 'Edit';
        }
    }

    showFeedback(message, type = 'info') {
        const feedback = document.createElement('div');
        Object.assign(feedback.style, {
            position: 'fixed',
            bottom: '20px',
            right: '20px',
            padding: '12px 24px',
            borderRadius: '4px',
            color: 'white',
            zIndex: '1000001',
            animation: 'fadeIn 0.3s, fadeOut 0.3s 2.7s',
            backgroundColor: type === 'error' ? '#f44336' :
                           type === 'warning' ? '#ff9800' : '#4CAF50'
        });
        
        feedback.textContent = message;
        document.body.appendChild(feedback);
        
        setTimeout(() => feedback.remove(), 3000);
    }

    startVoiceEdit() {
        // Use Web Speech API for local streaming and then server for formatting
        if (speechManager.isRecording) {
            speechManager.stopRecording();
            return;
        }

        const voiceButton = this.floatingMenu.querySelector('button:not([class*="submit"])');
        const input = this.floatingMenu.querySelector('input');
        
        voiceButton.innerHTML = '⏹️';
        voiceButton.style.backgroundColor = '#f44336';
        
        // Start recording with edit mode and callback
        speechManager.startRecording(null, true, (formattedText) => {
            // When transcription is complete and formatted, populate the input
            if (input && this.floatingMenu) {
                input.value = formattedText;
                
                voiceButton.innerHTML = '🎙️';
                voiceButton.style.backgroundColor = '#4CAF50';
            }
        });
    }
}

class SpeechManager {
    constructor() {
        this.recognition = null;
        this.isRecording = false;
        this.transcriptionElement = null;
        this.finalTranscription = '';
        this.interimTranscription = '';
        this.targetElement = null;
        this.isEditMode = false;
        this.editCallback = null;
        this.setupSpeechRecognition();
    }

    setupSpeechRecognition() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            console.warn('Web Speech API is not supported in this browser');
            return;
        }

        // Create SpeechRecognition object
        const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.recognition = new SpeechRecognitionAPI();
        
        // Configure recognition
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.maxAlternatives = 1;
        
        // Set language dynamically
        this.recognition.lang = document.documentElement.lang === 'ru' ? 'ru-RU' : 'en-US';
        
        // Set up event listeners
        this.recognition.onstart = () => {
            this.isRecording = true;
            console.log('Speech recognition started');
        };
        
        this.recognition.onend = () => {
            this.isRecording = false;
            console.log('Speech recognition ended');
            this.removeTranscriptionElement();
            
            // Send final transcription to server for formatting if needed
            if (this.finalTranscription) {
                this.sendToServerForFormatting();
            }
        };

        this.recognition.onresult = (event) => {
            this.interimTranscription = '';
            let finalTranscript = '';
            
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript;
                } else {
                    this.interimTranscription += event.results[i][0].transcript;
                }
            }

            if (finalTranscript) {
                this.finalTranscription += ' ' + finalTranscript;
                this.finalTranscription = this.finalTranscription.trim();
            }
            
            this.updateTranscriptionDisplay();
        };
        
        this.recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            this.removeTranscriptionElement();
        };
    }
    
    startRecording(targetElement = null, isEditMode = false, callback = null) {
        if (!this.recognition) {
            console.error('Speech recognition not available');
            this.showPermissionFeedback('Speech recognition not supported in this browser');
            return false;
        }
        
        this.targetElement = targetElement;
        this.isEditMode = isEditMode;
        this.editCallback = callback;
        this.finalTranscription = '';
        this.interimTranscription = '';
        
        // Check if we need to request microphone permission
        navigator.permissions.query({ name: 'microphone' }).then(permissionStatus => {
            console.log('Microphone permission status:', permissionStatus.state);
            
            // Set up permission change listener
            permissionStatus.onchange = () => {
                console.log('Permission status changed to:', permissionStatus.state);
                if (permissionStatus.state === 'granted') {
                    this.showPermissionFeedback('Microphone access granted!', 'success');
                } else if (permissionStatus.state === 'denied') {
                    this.showPermissionFeedback('Microphone access denied. Please enable in your browser settings.', 'error');
                }
            };
            
            if (permissionStatus.state === 'denied') {
                this.showPermissionFeedback('Microphone access denied. Please enable in your browser settings.', 'error');
                return false;
            }
        });
        
        this.createTranscriptionElement();
        
        try {
            this.recognition.start();
            return true;
        } catch (error) {
            console.error('Error starting speech recognition:', error);
            this.showPermissionFeedback('Could not start speech recognition. ' + error.message, 'error');
            return false;
        }
    }
    
    showPermissionFeedback(message, type = 'warning') {
        const feedback = document.createElement('div');
        Object.assign(feedback.style, {
            position: 'fixed',
            top: '20px',
            left: '50%',
            transform: 'translateX(-50%)',
            padding: '12px 24px',
            borderRadius: '4px',
            color: 'white',
            zIndex: '1000001',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
            backgroundColor: type === 'error' ? '#f44336' :
                           type === 'success' ? '#4CAF50' : '#ff9800'
        });
        
        feedback.textContent = message;
        document.body.appendChild(feedback);
        
        setTimeout(() => feedback.remove(), 5000);
    }
    
    stopRecording() {
        if (this.recognition && this.isRecording) {
            this.recognition.stop();
        }
    }
    
    createTranscriptionElement() {
        this.removeTranscriptionElement();
        
        this.transcriptionElement = document.createElement('div');
        this.transcriptionElement.className = 'milashka-transcription';
        Object.assign(this.transcriptionElement.style, {
            position: 'fixed',
            bottom: '20px',
            left: '20px',
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            padding: '10px 15px',
            borderRadius: '5px',
            boxShadow: '0 2px 10px rgba(0, 0, 0, 0.2)',
            zIndex: '1000000',
            maxWidth: '500px',
            maxHeight: '150px',
            overflowY: 'auto',
            fontSize: '14px',
            lineHeight: '1.4'
        });
        
        document.body.appendChild(this.transcriptionElement);
    }
    
    updateTranscriptionDisplay() {
        if (!this.transcriptionElement) return;
        
        const finalSpan = document.createElement('span');
        finalSpan.textContent = this.finalTranscription;
        
        const interimSpan = document.createElement('span');
        interimSpan.textContent = this.interimTranscription;
        Object.assign(interimSpan.style, {
            color: '#666',
            fontStyle: 'italic'
        });
        
        this.transcriptionElement.innerHTML = '';
        if (this.finalTranscription) {
            this.transcriptionElement.appendChild(finalSpan);
        }
        if (this.interimTranscription) {
            if (this.finalTranscription) {
                this.transcriptionElement.appendChild(document.createTextNode(' '));
            }
            this.transcriptionElement.appendChild(interimSpan);
        }
    }
    
    removeTranscriptionElement() {
        if (this.transcriptionElement) {
            this.transcriptionElement.remove();
            this.transcriptionElement = null;
        }
    }
    
    async sendToServerForFormatting() {
        if (!this.finalTranscription.trim()) return;
        
        try {
            const response = await chrome.runtime.sendMessage({
                type: "FORMAT_TRANSCRIPTION",
                text: this.finalTranscription,
                language: document.documentElement.lang || 'ru'
            });
            
            if (response.success) {
                const formattedText = response.formatted_text;
                
                if (this.isEditMode && this.editCallback) {
                    // For editing mode, call the callback with formatted text
                    this.editCallback(formattedText);
                } else if (this.targetElement && isValidInputElement(this.targetElement)) {
                    // For direct input mode, insert text at cursor position
                    const start = this.targetElement.selectionStart || 0;
                    const end = this.targetElement.selectionEnd || 0;
                    const originalText = this.targetElement.value || '';
                    
                    this.targetElement.value = originalText.substring(0, start) + formattedText + originalText.substring(end);
                    
                    this.targetElement.selectionStart = 
                    this.targetElement.selectionEnd = start + formattedText.length;
                    
                    this.targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                    this.targetElement.focus();
                }
            }
        } catch (error) {
            console.error("Failed to format transcription:", error);
        }
    }
}

const suggestionManager = new SuggestionManager();
const editingUI = new EditingUI();
const speechManager = new SpeechManager();

async function requestCompletion(text, element) {
    // Define language code at the top of the function to ensure it's available everywhere
    const langCode = document.documentElement.lang || 'ru';
    
    try {
        suggestionManager.cancelStream('requestCompletion_start');
        const requestId = ++suggestionManager.currentRequestId;
        suggestionManager.abortController = new AbortController();
        suggestionManager.streamInProgress = true;
        const apiUrl = window.MILASHKA_API_URL;
        
        const resp = await fetch(`${apiUrl}/completion/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_text: text, language: langCode }),
            signal: suggestionManager.abortController.signal
        });
        
        if (!resp.ok) throw new Error(`HTTP error! status: ${resp.status}`);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '', suggestion = text; // Start with current text
        
        while (true) {
            if (requestId !== suggestionManager.currentRequestId || !document.hasFocus()) {
                try { reader.cancel(); } catch (e) {}
                break;
            }
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            console.log(`[MilashkaAI] Received data chunk:`, buffer);
            const parts = buffer.split('\n\n');
            buffer = parts.pop() || '';
            
            for (const part of parts) {
                console.log(`[MilashkaAI] Processing part:`, part);
                if (part.startsWith('data: ')) {
                    const token = part.slice(6);
                    console.log(`[MilashkaAI] Extracted token: '${token}'`);
                    if (token && document.activeElement === element && 
                        requestId === suggestionManager.currentRequestId) {
                        // Show each token immediately
                        suggestion += token;
                        console.log(`[MilashkaAI] Displaying suggestion: '${suggestion.slice(-20)}...'`);
                        suggestionManager.displaySuggestion(element, suggestion);
                    }
                }
            }
        }
    } catch (error) {
        console.error('Completion error:', error);
        if (error.message?.includes('Extension context invalidated')) {
            showContextInvalidatedError();
            return;
        }
        
        // Determine if this is a "normal" error that should be silenced
        const isExpectedError = 
            // AbortErrors are expected during normal typing
            error.name?.includes('AbortError') || 
            error.message?.includes('abort') ||
            // DOMException often happens when streams are interrupted
            error instanceof DOMException || 
            // Also, the stream might have been canceled by us intentionally
            !suggestionManager.streamInProgress || 
            requestId !== suggestionManager.currentRequestId;
            
        // Only show error toast for meaningful errors, not for expected interruptions
        if (!isExpectedError) {
            console.warn('Showing error notification for:', error);
            suggestionManager.showToast('Failed to get completion', 'error');
        }
    } finally {
        suggestionManager.abortController = null;
        suggestionManager.streamInProgress = false;
    }

    // Fallback to non-streaming completion via background
    try {
        const response = await chrome.runtime.sendMessage({
            type: 'GET_COMPLETION',
            current_text: text,
            language: langCode // Use the langCode defined outside the try block
        });
        if (response && response.success && response.suggestion) {
            suggestionManager.displaySuggestion(element, response.suggestion);
        }
    } catch (error) {
        console.error('Fallback completion failed:', error);
    }
}

function handleInput(event) {
    const element = event.target;
    if (!isValidInputElement(element) || document.activeElement !== element || element.selectionStart !== element.selectionEnd) {
        suggestionManager.cancelStream('handleInput_invalid');
        suggestionManager.clearSuggestion();
        return;
    }
    
    // Cancel any existing stream immediately
    suggestionManager.cancelStream('handleInput_newInput');
    
    // Clear current suggestion
    suggestionManager.clearSuggestion();
    
    // Set active element
    suggestionManager.activeInputElement = element;
    
    // Clear existing debounce timer and set a new one with a longer delay
    // to prevent many requests while typing
    clearTimeout(suggestionManager.debounceTimer);
    suggestionManager.debounceTimer = setTimeout(() => {
        // Only request a completion if:
        // 1. We're not already streaming
// 2. We haven't just canceled due to keystrokes (still actively typing)
        if (!suggestionManager.streamInProgress && !suggestionManager.justCanceledByKeystroke) {
            const textBeforeCaret = element.value.substring(0, element.selectionStart);
            if (textBeforeCaret && textBeforeCaret.trim().length > 3) {
                console.log('[MilashkaAI] Requesting completion after debounce');
                requestCompletion(textBeforeCaret, element);
            }
        }
    }, 700);
}

function isValidInputElement(element) {
    return element.tagName === 'TEXTAREA' || 
           (element.tagName === 'INPUT' && element.type === 'text') ||
           element.isContentEditable;
}

document.addEventListener('input', handleInput, true);
document.addEventListener('selectionchange', () => {
    // Cancel suggestion if user selects text
    const el = document.activeElement;
    if (isValidInputElement(el) && (el.selectionStart !== el.selectionEnd)) {
        suggestionManager.cancelStream();
        suggestionManager.clearSuggestion();
    }
});

// Cancel any ongoing stream on any keydown to ensure immediate abort and restart
document.addEventListener('keydown', (e) => {
    // Only cancel if focused on valid input
    if (isValidInputElement(document.activeElement)) {
        // Cancel stream on any keystroke but don't start a new one immediately
        suggestionManager.cancelStream('globalKeydown');
        
        // Set a flag to indicate we just canceled due to keystroke
        // This will delay the next completion request
        suggestionManager.justCanceledByKeystroke = true;
        
        // Clear this flag after a short delay to allow completions again
        setTimeout(() => {
            suggestionManager.justCanceledByKeystroke = false;
        }, 1500);
    }
});

document.addEventListener('keydown', (event) => {
    if (suggestionManager.currentSuggestion && 
        suggestionManager.activeInputElement === event.target) {
        if (event.key === 'Tab' || event.key === 'Enter') {
            if (suggestionManager.acceptSuggestion()) {
                event.preventDefault();
                // After accepting, allow new completions
                setTimeout(() => handleInput({ target: event.target }), 0);
            }
        } else if (event.key === 'Escape') {
            suggestionManager.trackSuggestionFeedback(false);
            suggestionManager.cancelStream();
            suggestionManager.clearSuggestion();
            event.preventDefault();
        }
    } else if (event.key === 'Escape' && suggestionManager.streamInProgress) {
        // Allow Esc to always cancel the stream, even before first token
        suggestionManager.cancelStream();
        suggestionManager.clearSuggestion();
        event.preventDefault();
    }
}, true);

document.addEventListener('mouseup', (event) => {
    const selectedText = window.getSelection().toString().trim();
    if (selectedText.length > 0 && !editingUI.floatingMenu) {
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
            editingUI.currentSelectionRange = selection.getRangeAt(0);
            editingUI.showFloatingMenu(
                event.clientX,
                event.clientY + window.scrollY + 5,
                selectedText
            );
        }
    }
});

// Save the range and selection when text is selected
let lastSelectedRange = null;

document.addEventListener('mousedown', () => {
    // Clear the last selection when clicking
    lastSelectedRange = null;
});

document.addEventListener('selectionchange', () => {
    const selection = window.getSelection();
    if (selection.rangeCount > 0 && selection.toString().trim().length > 0) {
        // Store the range when a selection is made
        lastSelectedRange = selection.getRangeAt(0).cloneRange();
    }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SHOW_EDIT_UI") {
        const selectedText = request.selectedText;
        if (selectedText && lastSelectedRange) {
            // Restore the selection before showing the edit UI
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(lastSelectedRange);
            
            // Get coordinates for the floating menu
            const rect = lastSelectedRange.getBoundingClientRect();
            editingUI.showFloatingMenu(
                rect.right > window.innerWidth - 200 ? rect.left : rect.right, 
                rect.bottom + window.scrollY + 5,
                selectedText
            );
            
            // Store the current selection range for later use
            editingUI.currentSelectionRange = lastSelectedRange;
        } else if (selectedText) {
            // Fallback if no range was saved
            editingUI.showFloatingMenu(10, window.scrollY + 10, selectedText);
        }
    }
});

// Cancel stream when tab loses focus or visibility
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        suggestionManager.cancelStream();
    }
}, true);

// Cancel stream when input loses focus
document.addEventListener('blur', (event) => {
    if (event.target === suggestionManager.activeInputElement) {
        suggestionManager.cancelStream();
    }
}, true);

// Cancel stream when window loses focus
window.addEventListener('blur', () => {
    suggestionManager.cancelStream();
}, true);

// Clean up on page unload
window.addEventListener('unload', () => {
    suggestionManager.cancelStream();
}, true);
