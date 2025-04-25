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
        backgroundColor: 'black',
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
            opacity: 0.9, // Increased for better visibility
            zIndex: 1000, // Increased z-index to make sure it's on top
            width: '100%',
            height: '100%',
            overflow: 'hidden',
        });
        // Show only the part after the user's input
        const value = element.value || '';
        let caretPos = element.selectionStart || 0;
        let before = value.substring(0, caretPos);
        
        // Fix: suggestionText is already the completion part, don't try to substring it
        let after = suggestionText;
        
        // Log for debugging
        console.log('[MilashkaAI] Displaying suggestion:', {
            valueLength: value.length,
            caretPos,
            suggestionText,
            before: before.substring(Math.max(0, before.length - 10)),
            after: after.substring(0, Math.min(after.length, 20))
        });
        
        // Render ghost text after caret
        this.suggestionElement.innerHTML =
            `<span style="visibility:hidden">${this.escapeHtml(before)}</span><span style="color:#333;background-color:#f0f0f0;border-radius:2px;">${this.escapeHtml(after)}</span>`;
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
            backgroundColor: 'black',
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
        
        // Create and set microphone icon image
        const micIcon = document.createElement('img');
        const micIconUrl = chrome.runtime.getURL('icons/microphone.png');
        micIcon.src = micIconUrl;
        // Store absolute URL to prevent path issues
        micIcon.setAttribute('data-original-src', micIconUrl);
        micIcon.style.width = '16px';
        micIcon.style.height = '16px';
        voiceButton.appendChild(micIcon);
        
        voiceButton.onclick = () => {
            if (this.speechManager.isRecording) {
                // Reset to mic icon
                voiceButton.innerHTML = '';
                const micIcon = document.createElement('img');
                const micIconUrl = chrome.runtime.getURL('icons/microphone.png');
                micIcon.src = micIconUrl;
                // Store absolute URL to prevent path issues
                micIcon.setAttribute('data-original-src', micIconUrl);
                micIcon.style.width = '16px';
                micIcon.style.height = '16px';
                voiceButton.appendChild(micIcon);
                voiceButton.style.backgroundColor = 'black';
                this.speechManager.stopRecording();
            } else {
                voiceButton.innerHTML = '';
                const stopIcon = document.createElement('img');
                const stopIconUrl = chrome.runtime.getURL('icons/stop.png');
                stopIcon.src = stopIconUrl;
                stopIcon.setAttribute('data-original-src', stopIconUrl);
                stopIcon.style.width = '16px';
                stopIcon.style.height = '16px';
                voiceButton.appendChild(stopIcon);
                voiceButton.style.backgroundColor = 'black';
                const input = this.menu.querySelector('.milashka-edit-input');
                this.speechManager.startRecording(null, true, (formattedText) => {
                    if (input) {
                        input.value = formattedText;
                        // Reset to mic icon
                        voiceButton.innerHTML = '';
                        const micIcon = document.createElement('img');
                        const micIconUrl = chrome.runtime.getURL('icons/microphone.png');
                        micIcon.src = micIconUrl;
                        micIcon.setAttribute('data-original-src', micIconUrl);
                        micIcon.style.width = '16px';
                        micIcon.style.height = '16px';
                        voiceButton.appendChild(micIcon);
                        voiceButton.style.backgroundColor = 'black';
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
            backgroundColor: 'black',
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
            backgroundColor: 'black',
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
            backgroundColor: 'black', // All notification types are now black
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
        this.isRecording = false;
        this.transcriptionElement = null;
        this.finalTranscription = '';
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.targetElement = null;
        this.isEditMode = false;
        this.editCallback = null;
        this.listenerRegistered = false;
    }

    async startRecording(targetElement = null, isEditMode = false, callback = null) {
        this.targetElement = targetElement;
        this.isEditMode = isEditMode;
        this.editCallback = callback;
        this.finalTranscription = '';
        this.audioChunks = [];
        this.createTranscriptionElement();
        this.log('Requesting microphone access...');
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
            this.mediaRecorder.onstart = () => {
                this.isRecording = true;
                this.log('Recording started.');
                this.showPermissionFeedback('Recording started.', 'success');
            };
            this.mediaRecorder.ondataavailable = async (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                    this.log(`Audio chunk captured: ${event.data.size} bytes`);
                }
            };
            this.mediaRecorder.onerror = (e) => {
                this.log('MediaRecorder error: ' + e.error, 'error');
                this.showPermissionFeedback('Recording error: ' + e.error, 'error');
            };
            this.mediaRecorder.onstop = async () => {
                this.isRecording = false;
                this.log('Recording stopped. Sending audio for transcription...');
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                const arrayBuffer = await audioBlob.arrayBuffer();
                chrome.runtime.sendMessage({
                    type: 'TRANSCRIBE_AUDIO',
                    audioData: Array.from(new Uint8Array(arrayBuffer)),
                    audioType: 'audio/webm',
                    language: document.documentElement.lang || 'ru'
                }, (response) => {
                    if (response && response.transcription) {
                        this.finalTranscription = response.transcription;
                        this.updateTranscriptionDisplay();
                        this.log('Transcription received: ' + response.transcription);
                        if (this.isEditMode && this.editCallback) {
                            this.editCallback(response.transcription);
                        } else if (this.targetElement && isValidInputElement(this.targetElement)) {
                            const start = this.targetElement.selectionStart || 0;
                            const end = this.targetElement.selectionEnd || 0;
                            const originalText = this.targetElement.value || '';
                            this.targetElement.value = originalText.substring(0, start) + response.transcription + originalText.substring(end);
                            this.targetElement.selectionStart = this.targetElement.selectionEnd = start + response.transcription.length;
                            this.targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                            this.targetElement.focus();
                        }
                    } else {
                        this.log('Transcription failed: ' + (response && response.error), 'error');
                        this.showPermissionFeedback('Transcription failed: ' + (response && response.error), 'error');
                    }
                });
            };
            this.mediaRecorder.start();
        } catch (error) {
            this.log('Microphone access denied or error: ' + error.message, 'error');
            this.showPermissionFeedback('Microphone access denied or error: ' + error.message, 'error');
        }
    }

    stopRecording() {
        if (this.mediaRecorder && this.isRecording) {
            this.mediaRecorder.stop();
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
            this.log('Stopped recording and released microphone.');
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
        this.transcriptionElement.innerHTML = '';
        const finalSpan = document.createElement('span');
        finalSpan.textContent = this.finalTranscription;
        this.transcriptionElement.appendChild(finalSpan);
    }

    removeTranscriptionElement() {
        if (this.transcriptionElement) {
            this.transcriptionElement.remove();
            this.transcriptionElement = null;
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
            backgroundColor: type === 'error' ? 'red' : 'black'
        });
        feedback.textContent = message;
        document.body.appendChild(feedback);
        setTimeout(() => feedback.remove(), 5000);
    }

    log(message, type = 'info') {
        if (type === 'error') {
            console.error('[MilashkaAI][SpeechManager]', message);
        } else {
            console.log('[MilashkaAI][SpeechManager]', message);
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

    // Cancel any existing stream when the user types
    if (suggestionManager.streamInProgress) {
        suggestionManager.cancelStream('handleInput_newInput');
    }

    // Set new debounce timer
    suggestionManager.debounceTimer = setTimeout(async () => {
        console.log('[MilashkaAI] Autocomplete debounce triggered');
        if (!suggestionManager.streamInProgress && !suggestionManager.justCanceledByKeystroke) {
            const textBeforeCursor = element.value.substring(0, element.selectionStart);
            console.log('[MilashkaAI] Text before cursor:', textBeforeCursor?.substring(Math.max(0, textBeforeCursor.length - 50)));
            
            if (textBeforeCursor && textBeforeCursor.trim().length > 3) {
                console.log('[MilashkaAI] Sending streaming completion request');
                
                // Set up for streaming
                suggestionManager.streamInProgress = true;
                suggestionManager.activeInputElement = element;
                let lastSuggestionLength = 0;
                
                try {
                    // Request streaming completion
                    const streamResponse = await chrome.runtime.sendMessage({
                        type: "GET_COMPLETION_STREAM",
                        current_text: textBeforeCursor,
                        language: document.documentElement.lang || 'en'
                    });
                    
                    console.log('[MilashkaAI] Stream response initialized:', streamResponse);
                    
                    if (streamResponse && streamResponse.id) {
                        // Create abort controller for this stream
                        suggestionManager.abortController = new AbortController();
                        
                        // Store stream ID for debugging
                        const streamId = streamResponse.id || 'unknown';
                        console.log(`[MilashkaAI] Using stream ID: ${streamId}`);
                        
                        if (!streamId || streamId === 'unknown') {
                            console.error('[MilashkaAI] Invalid stream ID received');
                            suggestionManager.streamInProgress = false;
                        }
                        
                        // Process stream tokens as they arrive
                        while (!suggestionManager.abortController.signal.aborted) {
                            try {
                                if (!streamResponse || !streamResponse.id) {
                                    console.error('[MilashkaAI] Missing stream ID for READ_NEXT_CHUNK');
                                    break;
                                }
                                
                                const data = await chrome.runtime.sendMessage({
                                    type: "READ_NEXT_CHUNK",
                                    id: streamResponse.id
                                });
                                
                                if (!data) {
                                    console.error('[MilashkaAI] Received empty response from READ_NEXT_CHUNK');
                                    break;
                                }
                                
                                if (data.done) {
                                    console.log('[MilashkaAI] Stream complete');
                                    break;
                                }
                                
                                // Process and display each token as it arrives with visual feedback
                                if (data.messages && data.messages.length > 0) {
                                    const latestMessage = data.messages[data.messages.length - 1];
                                    // Only update UI if suggestion actually changed
                                    if (latestMessage.suggestion && 
                                        latestMessage.suggestion.length > lastSuggestionLength) {
                                        console.log('[MilashkaAI] Received token:', latestMessage.token);
                                        lastSuggestionLength = latestMessage.suggestion.length;
                                        // Only show the new completion, not the prompt + completion
                                        let completion = latestMessage.suggestion;
                                        if (completion.startsWith(textBeforeCursor)) {
                                            completion = completion.slice(textBeforeCursor.length);
                                        }
                                        suggestionManager.displaySuggestion(element, completion);
                                        // Briefly flash the suggestion to indicate new tokens (subtle visual feedback)
                                        if (suggestionManager.suggestionElement) {
                                            const originalOpacity = suggestionManager.suggestionElement.style.opacity;
                                            suggestionManager.suggestionElement.style.opacity = '0.9';
                                            setTimeout(() => {
                                                if (suggestionManager.suggestionElement) {
                                                    suggestionManager.suggestionElement.style.opacity = originalOpacity;
                                                }
                                            }, 100);
                                        }
                                    }
                                }
                            } catch (error) {
                                console.error('[MilashkaAI] Streaming completion error:', error);
                                break;
                            } finally {
                                suggestionManager.streamInProgress = false;
                            }
                        }
                    }
                } catch (error) {
                    console.error('[MilashkaAI] Streaming completion error:', error);
                } finally {
                    suggestionManager.streamInProgress = false;
                }
            } else {
                console.log('[MilashkaAI] Text too short for completion');
            }
        } else {
            console.log('[MilashkaAI] Completion skipped - stream in progress:', 
                        suggestionManager.streamInProgress, 
                        'just canceled:', 
                        suggestionManager.justCanceledByKeystroke);
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
    
    // Only attempt to capture if there's actually a selection
    const selection = window.getSelection();
    const hasSelection = selection && selection.toString().trim().length > 0;
    
    if (hasSelection && editingUI.capture()) {
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
