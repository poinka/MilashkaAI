console.log("Комплит content script loaded.");

// default API URL in case storage hasn't loaded yet
window.COMPLIT_API_URL = 'http://localhost:8000/api/v1';

// Enable detailed debug logging
const DEBUG_MODE = true;

function showContextInvalidatedError() {
    // Remove any existing error notification first
    const existing = document.getElementById('komplit-context-error');
    if (existing) existing.remove();
    
    const errorBar = document.createElement('div');
    errorBar.id = 'komplit-context-error';
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
        console.log(`[Комплит Toast] ${type}: ${message}`);
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
        if (DEBUG_MODE) {
            console.log('[Комплит] displaySuggestion called', { 
                element, 
                suggestionText, 
                textLength: suggestionText ? suggestionText.length : 0,
                textHex: suggestionText ? suggestionText.split('').map(c => c.charCodeAt(0).toString(16)).join(' ') : ''
            });
        }
        
        // Throttle updates
        const now = Date.now();
        if (now - this.lastUpdate < this.updateThrottle) return;
        this.lastUpdate = now;

        if (!suggestionText || suggestionText.trim() === '') {
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
        // Core state
        this.menu = null;
        this.originalText = null;
        this.targetElement = null;
        this.selectionStart = null;
        this.selectionEnd = null;
        this.speechManager = new SpeechManager(); // Add speech manager
    }

    capture() {
        // Capture selection state immediately when edit is triggered
        const selection = window.getSelection();
        const selectedText = selection.toString().trim();
        
        if (!selectedText) {
            console.warn('[MilashkaAI] No text selected');
            return false;
        }

        // Store original text and target
        this.originalText = selectedText;
        
        // Handle input/textarea elements
        if (document.activeElement instanceof HTMLInputElement || 
            document.activeElement instanceof HTMLTextAreaElement) {
            this.targetElement = document.activeElement;
            this.selectionStart = this.targetElement.selectionStart;
            this.selectionEnd = this.targetElement.selectionEnd;
            return true;
        }
        
        // Handle content editable and regular page text
        if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0);
            // Create simple object with just the info we need
            this.targetElement = {
                range: range.cloneRange(),
                isPageText: true
            };
            return true;
        }

        return false;
    }

    showFloatingMenu(x, y) {
        // Only show menu if we have a valid selection captured
        if (!this.originalText) {
            console.warn('[MilashkaAI] Cannot show menu without selection');
            return;
        }

        this.hideFloatingMenu();

        // Create menu container
        this.menu = document.createElement('div');
        this.menu.className = 'milashka-floating-menu';
        Object.assign(this.menu.style, {
            position: 'fixed',
            left: `${x}px`,
            top: `${y}px`,
            backgroundColor: 'white',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
            borderRadius: '4px',
            padding: '8px',
            zIndex: '1000000',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
        });

        // Create input container
        const inputWrapper = document.createElement('div');
        inputWrapper.style.display = 'flex';
        inputWrapper.style.gap = '8px';

        // Create voice button
        const voiceButton = document.createElement('button');
        Object.assign(voiceButton.style, {
            padding: '6px 12px',
            backgroundColor: '#4CAF50',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: '36px'
        });
        voiceButton.innerHTML = '🎙️';
        voiceButton.onclick = () => {
            if (this.speechManager.isRecording) {
                voiceButton.innerHTML = '🎙️';
                voiceButton.style.backgroundColor = '#4CAF50';
                this.speechManager.stopRecording();
            } else {
                voiceButton.innerHTML = '⏹️';
                voiceButton.style.backgroundColor = '#f44336';
                const input = this.menu.querySelector('.milashka-edit-input');
                this.speechManager.startRecording(null, true, (formattedText) => {
                    if (input) {
                        input.value = formattedText;
                        voiceButton.innerHTML = '🎙️';
                        voiceButton.style.backgroundColor = '#4CAF50';
                    }
                });
            }
        };

        // Create input field
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'milashka-edit-input';
        Object.assign(input.style, {
            width: '200px',
            padding: '6px',
            border: '1px solid #ddd',
            borderRadius: '4px',
            fontSize: '14px'
        });
        input.placeholder = 'Describe your edit';
        input.setAttribute('autocomplete', 'off');
        input.setAttribute('autocorrect', 'off');
        input.setAttribute('autocapitalize', 'off');
        input.setAttribute('spellcheck', 'false');
        
        input.addEventListener('mousedown', e => e.stopPropagation());
        input.addEventListener('keydown', e => e.stopPropagation());

        // Create buttons container
        const buttonWrapper = document.createElement('div');
        buttonWrapper.style.display = 'flex';
        buttonWrapper.style.gap = '4px';

        // Create edit button
        const editButton = document.createElement('button');
        editButton.className = 'milashka-edit-button';
        Object.assign(editButton.style, {
            padding: '6px 12px',
            backgroundColor: '#4CAF50',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            flex: 1
        });
        editButton.textContent = 'Edit';

        // Create cancel button
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

        // Wire up button events
        editButton.onclick = async () => {
            if (input.value) {
                editButton.disabled = true;
                editButton.textContent = 'Processing...';
                await this.performEdit(input.value);
                this.hideFloatingMenu();
            }
        };

        cancelButton.onclick = () => this.hideFloatingMenu();

        // Handle enter key in input
        input.onkeydown = async (e) => {
            if (e.key === 'Enter' && input.value) {
                editButton.disabled = true;
                editButton.textContent = 'Processing...';
                await this.performEdit(input.value);
                this.hideFloatingMenu();
            } else if (e.key === 'Escape') {
                this.hideFloatingMenu();
            }
        };

        // Assemble all components
        inputWrapper.appendChild(input);        // Add input field first
        inputWrapper.appendChild(voiceButton);  // Add voice button next to input
        buttonWrapper.appendChild(editButton);  // Add edit button
        buttonWrapper.appendChild(cancelButton); // Add cancel button
        
        // Add everything to menu in correct order
        this.menu.appendChild(inputWrapper);
        this.menu.appendChild(buttonWrapper);
        document.body.appendChild(this.menu);

        // Add global click handler
        document.addEventListener('mousedown', this.handleClickOutside);
    }

    handleClickOutside = (e) => {
        if (this.menu && !this.menu.contains(e.target)) {
            this.hideFloatingMenu();
        }
    };

    hideFloatingMenu() {
        if (this.menu) {
            this.menu.remove();
            this.menu = null;
            document.removeEventListener('mousedown', this.handleClickOutside);
        }
    }

    async performEdit(prompt) {
        if (!this.originalText || !this.targetElement) {
            console.error('[MilashkaAI] Cannot edit: no valid selection');
            this.showFeedback('Cannot edit: no valid selection', 'error');
            return;
        }

        try {
            console.log('[MilashkaAI] Sending edit request:', {
                text: this.originalText,
                prompt: prompt
            });

            const response = await chrome.runtime.sendMessage({
                type: "EDIT_TEXT",
                selected_text: this.originalText,
                prompt: prompt,
                language: document.documentElement.lang || 'en'
            });

            console.log('[MilashkaAI] Received edit response:', response);

            console.log('[MilashkaAI] Response:', response);
            
            // The edited_text is actually in response.data.edited_text
            if (!response.edited_text) {
                throw new Error(response.error || 'No edited text received');
            }

            this.applyEdit(response.edited_text);
            this.showFeedback('Edit applied successfully', 'success');

        } catch (error) {
            console.error('[MilashkaAI] Edit failed:', error);
            this.showFeedback(`Edit failed: ${error.message}`, 'error');
        }
    }

    applyEdit(newText) {
        if (!this.targetElement) {
            console.error('[MilashkaAI] Cannot apply edit: no target element');
            return;
        }

        try {
            if (this.targetElement.isPageText) {
                // Handle page text edits
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(this.targetElement.range);
                
                const range = selection.getRangeAt(0);
                range.deleteContents();
                
                if (/<[a-z][\s\S]*>/i.test(newText)) {
                    // Handle HTML content
                    const temp = document.createElement('div');
                    temp.innerHTML = newText;
                    const fragment = document.createDocumentFragment();
                    while (temp.firstChild) {
                        fragment.appendChild(temp.firstChild);
                    }
                    range.insertNode(fragment);
                } else {
                    // Handle plain text
                    range.insertNode(document.createTextNode(newText));
                }
                
                selection.collapseToEnd();
                
            } else {
                // Handle input/textarea edits
                const element = this.targetElement;
                const before = element.value.substring(0, this.selectionStart);
                const after = element.value.substring(this.selectionEnd);
                element.value = before + newText + after;
                
                // Update cursor position
                const newPosition = this.selectionStart + newText.length;
                element.selectionStart = element.selectionEnd = newPosition;
                
                // Trigger input event
                element.dispatchEvent(new Event('input', { bubbles: true }));
            }
        } catch (error) {
            console.error('[MilashkaAI] Error applying edit:', error);
            throw error;
        } finally {
            // Clear state
            this.targetElement = null;
            this.selectionStart = null;
            this.selectionEnd = null;
            this.originalText = null;
        }
    }

    showFeedback(message, type = 'info') {
        const toast = document.createElement('div');
        Object.assign(toast.style, {
            position: 'fixed',
            bottom: '20px',
            right: '20px',
            padding: '12px 24px',
            borderRadius: '4px',
            color: 'white',
            zIndex: '1000001',
            backgroundColor: 
                type === 'error' ? '#f44336' :
                type === 'warning' ? '#ff9800' : '#4CAF50',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
            animation: 'fadeInOut 3s ease-in-out'
        });
        
        // Add fadeInOut animation
        const style = document.createElement('style');
        style.textContent = `
            @keyframes fadeInOut {
                0% { opacity: 0; transform: translateY(20px); }
                10% { opacity: 1; transform: translateY(0); }
                90% { opacity: 1; transform: translateY(0); }
                100% { opacity: 0; transform: translateY(-20px); }
            }
        `;
        document.head.appendChild(style);
        
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
            style.remove();
        }, 3000);
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

function isValidInputElement(element) {
    return (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) &&
           !element.classList.contains('milashka-edit-input');
}

// Initialize managers and UI
const suggestionManager = new SuggestionManager();
const editingUI = new EditingUI();

// Handle input events for autocomplete
document.addEventListener('input', async (event) => {
    const element = event.target;
    
    // Skip if element is not valid for suggestions or is our edit menu input
    if (!isValidInputElement(element)) {
        return;
    }

    // Clear any existing debounce timer
    if (suggestionManager.debounceTimer) {
        clearTimeout(suggestionManager.debounceTimer);
    }

    // Set new debounce timer
    suggestionManager.debounceTimer = setTimeout(async () => {
        if (!suggestionManager.streamInProgress && !suggestionManager.justCanceledByKeystroke) {
            const textBeforeCursor = element.value.substring(0, element.selectionStart);
            if (textBeforeCursor && textBeforeCursor.trim().length > 3) {
                try {
                    const response = await chrome.runtime.sendMessage({
                        type: "GET_COMPLETION",
                        text: textBeforeCursor,
                        language: document.documentElement.lang || 'en'
                    });
                    
                    if (response.success && response.completion) {
                        suggestionManager.displaySuggestion(element, textBeforeCursor + response.completion);
                    }
                } catch (error) {
                    console.error('[MilashkaAI] Completion error:', error);
                }
            }
        }
    }, 700);
});

// Handle special keys for suggestions
document.addEventListener('keydown', (event) => {
    const element = event.target;
    if (!isValidInputElement(element)) return;

    if (event.key === 'Tab' && !event.shiftKey && suggestionManager.currentSuggestion) {
        event.preventDefault();
        suggestionManager.acceptSuggestion();
    } else if (event.key === 'Escape') {
        suggestionManager.cancelStream('globalKeydown');
        suggestionManager.clearSuggestion();
    }
}, true);

// Handle selection-based editing
document.addEventListener('mouseup', (event) => {
    // Don't show menu if click was inside our own UI
    if (editingUI.menu && editingUI.menu.contains(event.target)) {
        return;
    }
    
    if (editingUI.capture()) {
        editingUI.showFloatingMenu(
            event.clientX,
            event.clientY + window.scrollY + 5
        );
    }
});

// Handle context menu edit requests
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SHOW_EDIT_UI") {
        if (editingUI.capture()) {
            // Position menu near the selection
            const selection = window.getSelection();
            const range = selection.getRangeAt(0);
            const rect = range.getBoundingClientRect();
            
            editingUI.showFloatingMenu(
                rect.right > window.innerWidth - 220 ? rect.left : rect.right,
                rect.bottom + window.scrollY + 5
            );
        }
    }
});

// Clean up on page unload
window.addEventListener('unload', () => {
    editingUI.hideFloatingMenu();
});
