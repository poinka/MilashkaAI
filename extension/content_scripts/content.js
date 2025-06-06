console.log("Комплит content script loaded.");

// default API URL in case storage hasn't loaded yet
window.COMPLIT_API_URL = 'http://localhost:8000/api/v1';

// Enable detailed debug logging
const DEBUG_MODE = true;

// Track extension connection state
let isExtensionConnected = true;
let connectionCheckInterval = null;

function checkExtensionConnection() {
    if (!chrome || !chrome.runtime) {
        isExtensionConnected = false;
        showContextInvalidatedError();
        return false;
    }
    
    try {
        // Attempt to use the chrome.runtime API as a test
        chrome.runtime.getURL('');
        
        // If we get here, connection is working
        if (!isExtensionConnected) {
            // We've reconnected!
            isExtensionConnected = true;
            hideContextInvalidatedError();
            return true;
        }
        return true;
    } catch (e) {
        isExtensionConnected = false;
        showContextInvalidatedError();
        return false;
    }
}

// Start checking connection periodically
function startConnectionMonitoring() {
    if (connectionCheckInterval) return;
    connectionCheckInterval = setInterval(checkExtensionConnection, 5000); // Check every 5 seconds
    checkExtensionConnection(); // Check immediately
}

// Initialize connection monitoring
startConnectionMonitoring();

function showContextInvalidatedError() {
    // Remove any existing error notification first
    const existing = document.getElementById('milashka-context-error');
    if (existing) return; // Already showing
    
    const errorBar = document.createElement('div');
    errorBar.id = 'milashka-context-error';
    Object.assign(errorBar.style, {
        position: 'fixed',
        top: '0',
        left: '0',
        right: '0',
        backgroundColor: 'rgba(0,0,0,0.9)',
        color: 'white',
        padding: '14px',
        textAlign: 'center',
        zIndex: '999999',
        cursor: 'pointer',
        fontFamily: 'Montserrat, system-ui',
        fontWeight: 500,
        boxShadow: '0 2px 10px rgba(0,0,0,0.3)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        gap: '10px',
        transition: 'all 0.3s ease'
    });
    
    // Add warning icon
    const icon = document.createElement('span');
    icon.innerHTML = '⚠️';
    icon.style.fontSize = '18px';
    errorBar.appendChild(icon);
    
    // Add text content
    const textSpan = document.createElement('span');
    textSpan.textContent = '"Комплит" отключен. Нажмите здесь, чтобы перезагрузить страницу';
    errorBar.appendChild(textSpan);
    
    // Add reload button
    const reloadBtn = document.createElement('button');
    reloadBtn.textContent = 'Перезагрузить';
    Object.assign(reloadBtn.style, {
        marginLeft: '10px',
        padding: '6px 14px',
        backgroundColor: 'white',
        color: 'black',
        border: 'none',
        borderRadius: '20px',
        cursor: 'pointer',
        fontFamily: 'Montserrat, system-ui',
        fontWeight: 500,
        fontSize: '14px'
    });
    errorBar.appendChild(reloadBtn);
    
    // Click handlers
    errorBar.onclick = () => window.location.reload();
    reloadBtn.onclick = (e) => {
        e.stopPropagation();
        window.location.reload();
    };
    
    // Animation
    errorBar.style.transform = 'translateY(-100%)';
    document.body.appendChild(errorBar);
    
    // Animate in
    setTimeout(() => {
        errorBar.style.transform = 'translateY(0)';
    }, 10);
}

function hideContextInvalidatedError() {
    const existing = document.getElementById('milashka-context-error');
    if (!existing) return;
    
    // Animate out
    existing.style.transform = 'translateY(-100%)';
    
    // Remove after animation
    setTimeout(() => {
        if (existing.parentNode) {
            existing.parentNode.removeChild(existing);
        }
    }, 300);
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
        console.log(`[Complete] cancelStream called from: ${source}`);
        if (this.abortController) {
            // Save the stack trace before aborting
            const stackTrace = new Error().stack;
            console.log('[Complete] Abort controller stack:', stackTrace);
            
            this.abortController.abort();
            this.abortController = null;
            console.log(`[Complete] Completion cancelled from: ${source}`);
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
            console.log('[Complete] ensureOverlay: already wrapped');
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
            console.log('[Complete] ensureOverlay: wrapper created');
            return wrapper;
        } catch (e) {
            console.error('[Complete] ensureOverlay: failed to create overlay', e);
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
            console.error('[Complete] displaySuggestion: could not get wrapper for element', element);
            return;
        }
        // Remove any old overlays
        const oldOverlays = wrapper.querySelectorAll('.milashka-suggestion-overlay');
        oldOverlays.forEach(node => node.remove());
        // Create overlay if needed
        this.suggestionElement = document.createElement('div');
        this.suggestionElement.className = 'milashka-suggestion-overlay';
        // Style to match input - modern, transparent, Montserrat, italic, adaptive color
        const style = window.getComputedStyle(element);
        Object.assign(this.suggestionElement.style, {
            position: 'absolute',
            left: style.paddingLeft,
            top: style.paddingTop,
            color: 'rgba(133, 133, 133, 0.66)',
            backgroundColor: 'transparent',
            fontFamily: "'Montserrat', system-ui, sans-serif",
            fontWeight: 500,
            pointerEvents: 'none',
            fontSize: style.fontSize,
            whiteSpace: 'pre-wrap',
            opacity: 1,
            zIndex: 999999,
            width: '100%',
            height: '100%',
            overflow: 'hidden',
            border: 'none',
            transition: 'opacity 0.2s'
        });
        // Show only the part after the user's input
        const value = element.value || '';
        let caretPos = element.selectionStart || 0;
        let before = value.substring(0, caretPos);
        
        // Fix: suggestionText is already the completion part, don't try to substring it
        let after = suggestionText;
        
        // Log for debugging
        console.log('[Complete] Displaying suggestion:', {
            valueLength: value.length,
            caretPos,
            suggestionText,
            before: before.substring(Math.max(0, before.length - 10)),
            after: after.substring(0, Math.min(after.length, 20))
        });
        
        // Render ghost text after caret
        this.suggestionElement.innerHTML =
            `<span style="visibility:hidden">${this.escapeHtml(before)}</span><span>${this.escapeHtml(after)}</span>`;
        wrapper.appendChild(this.suggestionElement);
        console.log('[Complete] displaySuggestion: overlay appended');
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
        this.abortController = null; // For aborting in-progress edit requests
        this.editInProgress = false; // Flag to track if an edit is in progress
    }

    capture() {
        // Capture selection state immediately when edit is triggered
        const selection = window.getSelection();
        const selectedText = selection.toString().trim();
        
        if (!selectedText) {
            console.warn('[Complete] No text selected');
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
            console.warn('[Complete] Cannot show menu without selection');
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
            zIndex: '1000000',
            display: 'flex',
            flexDirection: 'column',
        });
        
        ContextMenuStyler.applyStylesToMenu(this.menu);
        
        // Create input container
        const inputWrapper = document.createElement('div');
        inputWrapper.style.display = 'flex';
        inputWrapper.style.gap = '8px';

        // Create voice button with capsule shape
        const voiceButton = ContextMenuStyler.createVoiceButton();
        // Set initial icon state to microphone (not recording)
        ContextMenuStyler.updateMicIcon(voiceButton, false); 
        voiceButton.onclick = () => {
            if (this.speechManager.isRecording) {
                ContextMenuStyler.updateMicIcon(voiceButton, false);
                this.speechManager.stopRecording();
            } else {
                ContextMenuStyler.updateMicIcon(voiceButton, true);
                const input = this.menu.querySelector('.milashka-edit-input');
                // Голосовой ввод: сразу отправляем результат в LLM, как альтернативу ручному вводу
                this.speechManager.startRecording(null, true, async (formattedText) => {
                    if (input) {
                        input.value = formattedText;
                        ContextMenuStyler.updateMicIcon(voiceButton, false);
                        input.focus();
                        // Показать анимацию подсветки
                        const originalBg = input.style.backgroundColor;
                        input.style.backgroundColor = '#e6f7ff';
                        setTimeout(() => {
                            input.style.backgroundColor = originalBg;
                        }, 500);
                        // Сразу отправить на LLM (форматирование)
                        editButton.disabled = true;
                        editButton.textContent = 'Форматирование...';
                        await this.performEdit(formattedText);
                        this.hideFloatingMenu();
                    }
                });
            }
        };

        // Create input field with light gray background and capsule shape
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'milashka-edit-input';
        ContextMenuStyler.styleInputField(input);
        input.setAttribute('autocomplete', 'off');
        input.setAttribute('autocorrect', 'off');
        input.setAttribute('autocapitalize', 'off');
        input.setAttribute('spellcheck', 'false');
        
        input.addEventListener('mousedown', e => e.stopPropagation());
        input.addEventListener('keydown', e => e.stopPropagation());

        // Create buttons container with improved styling for centering
        const buttonWrapper = document.createElement('div');
        Object.assign(buttonWrapper.style, {
            display: 'flex',
            gap: '10px',
            width: '100%',
            justifyContent: 'center',
            marginTop: '4px'
        });

        // Create edit button with capsule shape and fixed width
        const editButton = ContextMenuStyler.createActionButton('Изменить', true);
        editButton.onclick = async () => {
            if (input.value) {
                editButton.disabled = true;
                editButton.textContent = 'Форматирование...';
                await this.performEdit(input.value);
                this.hideFloatingMenu();
            }
        };

        // Create cancel button with capsule shape and fixed width
        const cancelButton = ContextMenuStyler.createActionButton('Отмена', false);
        cancelButton.onclick = () => {
            // First abort any in-progress requests, then hide the menu
            this.abortRequests();
            this.hideFloatingMenu();
        };

        // Handle enter key in input
        input.onkeydown = async (e) => {
            if (e.key === 'Enter' && input.value) {
                editButton.disabled = true;
                editButton.textContent = 'Форматирование...';
                await this.performEdit(input.value);
                this.hideFloatingMenu();
            } else if (e.key === 'Escape') {
                // First abort any in-progress requests, then hide the menu
                this.abortRequests();
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

        // Focus the input field automatically
        setTimeout(() => input.focus(), 50);

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
            
            // Abort any in-progress requests when menu is closed
            this.abortRequests();
        }
    }
    
    abortRequests() {
        // Abort any in-progress edit requests
        if (this.abortController) {
            console.log('[Complete] Aborting in-progress edit request');
            this.abortController.abort();
            this.abortController = null;
            this.editInProgress = false;
        }
        
        // Also abort any suggestion/completion requests from the suggestionManager
        if (suggestionManager && suggestionManager.streamInProgress) {
            console.log('[Complete] Aborting in-progress suggestion stream from EditingUI');
            suggestionManager.cancelStream('editingUI_cancel');
        }
    }

    async performEdit(prompt) {
        if (!this.originalText || !this.targetElement) {
            console.error('[Complete] Cannot edit: no valid selection');
            this.showFeedback('Cannot edit: no valid selection', 'error');
            return;
        }

        // Abort any existing in-progress request
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        
        // Create a new AbortController for this request
        this.abortController = new AbortController();
        this.editInProgress = true;

        try {
            console.log('[Complete] Sending edit request:', {
                text: this.originalText,
                prompt: prompt
            });

            // Create a signal for detecting when our request is aborted
            const signal = this.abortController.signal;
            
            // Create a promise that will reject when the abort signal is triggered
            const abortPromise = new Promise((_, reject) => {
                signal.addEventListener('abort', () => {
                    reject(new Error('Edit request was cancelled'));
                });
            });
            
            // Create the message promise
            const messagePromise = chrome.runtime.sendMessage({
                type: "EDIT_TEXT",
                selected_text: this.originalText,
                prompt: prompt,
                language: document.documentElement.lang || 'en'
            });
            
            // Race the message promise against the abort promise
            const response = await Promise.race([messagePromise, abortPromise]);

            console.log('[Complete] Received edit response:', response);
            
            // If we've gotten this far, the request was not aborted
            this.editInProgress = false;
            this.abortController = null;
            
            // The edited_text is actually in response.data.edited_text
            if (!response.edited_text) {
                throw new Error(response.error || 'No edited text received');
            }

            this.applyEdit(response.edited_text);
            this.showFeedback('Edit applied successfully', 'success');

        } catch (error) {
            this.editInProgress = false;
            this.abortController = null;
            
            // Don't show an error notification if the request was deliberately cancelled
            if (error.message === 'Edit request was cancelled') {
                console.log('[Complete] Edit request was cancelled');
            } else {
                console.error('[Complete] Edit failed:', error);
                this.showFeedback(`Edit failed: ${error.message}`, 'error');
            }
        }
    }

    applyEdit(newText) {
        if (!this.targetElement) {
            console.error('[Complete] Cannot apply edit: no target element');
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
            console.error('[Complete] Error applying edit:', error);
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
            borderRadius: '20px',
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
        
        // Only create transcription element for non-edit mode
        if (!isEditMode) {
            this.createTranscriptionElement();
        }
        
        this.log('Requesting microphone access...');
        try {
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
            
            this.mediaRecorder = new MediaRecorder(stream, { 
                mimeType: mimeType,
                audioBitsPerSecond: 128000 
            });
            this.mediaRecorder.onstart = () => {
                this.isRecording = true;
                this.log('Recording started.');
                this.showPermissionFeedback('Запись началась...', 'success');
            };
            this.mediaRecorder.ondataavailable = async (event) => {
                if (event.data.size > 0) {
                    this.audioChunks.push(event.data);
                    this.log(`Audio chunk captured: ${event.data.size} bytes`);
                }
            };
            this.mediaRecorder.onerror = (e) => {
                this.log('MediaRecorder error: ' + e.error, 'error');
                this.showPermissionFeedback('Ошибка записи: ' + e.error, 'error');
            };
            this.mediaRecorder.onstop = async () => {
                this.isRecording = false;
                this.log('Recording stopped. Sending audio for transcription...');
                this.showPermissionFeedback('Обработка записи...', 'info');
                
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
                        
                        // For edit mode, directly pass to callback without showing transcription element
                        if (this.isEditMode && this.editCallback) {
                            console.log('Passing transcription directly to edit input:', this.finalTranscription);
                            this.editCallback(this.finalTranscription);
                        } else {
                            // For regular mode, update the transcription display
                            this.updateTranscriptionDisplay();
                            this.log('Transcription received: ' + response.transcription);
                            
                            // Insert text into target if available
                            if (this.targetElement && isValidInputElement(this.targetElement)) {
                                const start = this.targetElement.selectionStart || 0;
                                const end = this.targetElement.selectionEnd || 0;
                                const originalText = this.targetElement.value || '';
                                this.targetElement.value = originalText.substring(0, start) + response.transcription + originalText.substring(end);
                                this.targetElement.selectionStart = this.targetElement.selectionEnd = start + response.transcription.length;
                                this.targetElement.dispatchEvent(new Event('input', { bubbles: true }));
                                this.targetElement.focus();
                            }
                        }
                        
                        this.showPermissionFeedback('Транскрипция готова', 'success');
                    } else {
                        this.log('Transcription failed: ' + (response && response.error), 'error');
                        this.showPermissionFeedback('Ошибка транскрипции: ' + (response && response.error), 'error');
                    }
                });
            };
            this.mediaRecorder.start();
        } catch (error) {
            this.log('Microphone access denied or error: ' + error.message, 'error');
            this.showPermissionFeedback('Ошибка доступа к микрофону: ' + error.message, 'error');
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
            borderRadius: '20px',
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
            console.error('[Complete][SpeechManager]', message);
        } else {
            console.log('[Complete][SpeechManager]', message);
        }
    }
}

function isValidInputElement(element) {
    return (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) &&
           !element.classList.contains('milashka-edit-input');
}

/**
 * ContextMenuStyler - Provides styling and UI enhancement functions for the context menu
 * Merged from menu-styles.js
 */
class ContextMenuStyler {
    static applyStylesToMenu(menu) {
        // Add Montserrat font if not already added
        if (!document.getElementById('milashka-font-style')) {
            const fontStyle = document.createElement('style');
            fontStyle.id = 'milashka-font-style';
            fontStyle.textContent = `
                @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600&display=swap');
                .milashka-floating-menu, .milashka-floating-menu * {
                    font-family: 'Montserrat', sans-serif !important;
                }
            `;
            document.head.appendChild(fontStyle);
        }
        
        // Enhance main menu container - more rounded with better shadow
        Object.assign(menu.style, {
            backgroundColor: 'white',
            boxShadow: '0 4px 20px rgba(0,0,0,0.12)', // Lighter and more spread out shadow
            borderRadius: '30px', // Much more rounded corners (higher than buttons' 20px radius)
            padding: '16px', // Increased padding for more breathing room
            gap: '12px', // Increased gap between elements
            minWidth: '280px' // Set minimum width for better proportions
        });
    }
    
    static createVoiceButton() {
        const voiceButton = document.createElement('button');
        Object.assign(voiceButton.style, {
            padding: '6px 12px',
            backgroundColor: 'black',
            color: 'white',
            border: 'none',
            borderRadius: '30px', // Capsule shape
            cursor: 'pointer',
            fontSize: '16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: '36px',
            height: '36px'
        });
        
        return voiceButton;
    }
    
    static updateMicIcon(button, isRecording = false) {
        // Clear previous content
        button.innerHTML = '';
        
        // Create appropriate icon
        const icon = document.createElement('img');
        // Fix paths to use browser_extension:// protocol instead of relative paths
        const iconPath = isRecording ? 
            '../icons/stop.png' : 
            '../icons/microphone.png';
        try {
            // Check if chrome.runtime is available
            if (chrome && chrome.runtime) {
                // Use extension URL for correct path
                const iconUrl = chrome.runtime.getURL(iconPath);
                icon.src = iconUrl;
                
                // Store path for future reference
                icon.setAttribute('data-original-src', iconUrl);
                
                // Debug logging to help identify path issues
                console.log('[Complete] Mic icon URL:', iconUrl);
            } else {
                // Fallback to using a data URI for microphone icon
                if (isRecording) {
                    // Simple stop icon as data URI
                    icon.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" fill="white"/></svg>';
                } else {
                    // Simple microphone icon as data URI
                    icon.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="6" r="3" fill="white"/><rect x="7" y="9" width="2" height="4" fill="white"/><rect x="5" y="13" width="6" height="1" fill="white"/></svg>';
                }
                console.warn('[Complete] Using fallback icons due to extension context issues');
            }
        } catch (e) {
            // Fallback in case of errors
            console.error('[Complete] Error loading icon:', e);
            icon.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" stroke="white" fill="none"/></svg>';
        }
        
        // Style icon - make it slightly bigger
        icon.style.width = '20px'; // Increased from 18px
        icon.style.height = '20px'; // Increased from 18px
        
        // Add to button
        button.appendChild(icon);
        
        return icon;
    }
    
    static styleInputField(input) {
        Object.assign(input.style, {
            width: '200px',
            padding: '8px 12px',
            border: '1px solid #e0e0e0',
            backgroundColor: '#f5f5f5',
            borderRadius: '30px',
            fontSize: '14px',
            outline: 'none',
            color: '#111', // Make text black
            fontWeight: '600', // Make text bolder
            fontFamily: 'Montserrat, system-ui',
        });
        // Change placeholder to Russian
        input.placeholder = 'Что изменить?';
        return input;
    }
    
    static createActionButton(text, isPrimary = true) {
        const button = document.createElement('button');
        
        Object.assign(button.style, {
            padding: '12px 16px', // Increased padding for bigger buttons
            backgroundColor: 'black',
            color: 'white',
            border: 'none',
            borderRadius: '30px', // Capsule shape
            cursor: 'pointer',
            flex: '1', // Make buttons expand to fill available space
            fontSize: '14px',
            fontWeight: '500',
            transition: 'all 0.2s ease',
            minHeight: '44px', // Increased from 40px for bigger buttons
            boxShadow: '0 2px 6px rgba(0,0,0,0.1)' // Subtle shadow for all buttons
        });
        
        // Set Russian text
        button.textContent = isPrimary ? 'Изменить' : 'Отмена';
        
        // Add hover effect for cancel button with red inner shadow
        if (!isPrimary) {
            // Initially add a subtle red inner shadow (more spread out)
            button.style.boxShadow = 'inset 0 0 3px 1px rgba(255,0,0,0.0), 0 2px 6px rgba(0,0,0,0.1)';
            
            button.addEventListener('mouseover', () => {
                // Stronger red inner shadow on hover
                button.style.boxShadow = 'inset 0 0 8px 4px rgba(255,0,0,0.6), 0 2px 6px rgba(0,0,0,0.1)';
            });
            
            button.addEventListener('mouseout', () => {
                // Return to subtle red inner shadow
                button.style.boxShadow = 'inset 0 0 3px 1px rgba(255,0,0,0.0), 0 2px 6px rgba(0,0,0,0.1)';
            });
        }
        
        return button;
    }
}

// Initialize managers and UI
const suggestionManager = new SuggestionManager();
const editingUI = new EditingUI();

// Обработчик сообщений для показа меню
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SHOW_EDIT_UI") {
        console.log('[Complete] Received SHOW_EDIT_UI request');
        if (editingUI.capture()) {
            // Position menu near the selection
            const selection = window.getSelection();
            const range = selection.getRangeAt(0);
            const rect = range.getBoundingClientRect();
            
            // Сохраняем выделение
            const savedRange = range.cloneRange();
            
            editingUI.showFloatingMenu(
                rect.right > window.innerWidth - 220 ? rect.left : rect.right,
                rect.bottom + window.scrollY + 5
            );
            
            // Восстанавливаем выделение после показа меню
            setTimeout(() => {
                try {
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(savedRange);
                } catch (e) {
                    console.error('[Complete] Error restoring selection:', e);
                }
            }, 100);
        }
    }
});
// --- Конец исправления выделения ---

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
        console.log('[Complete] Autocomplete debounce triggered');
        const textBeforeCursor = element.value.substring(0, element.selectionStart);
        if (textBeforeCursor && textBeforeCursor.trim().length > 1) {
            console.log('[Complete] Fetching completion via GET_COMPLETION:', textBeforeCursor);
            chrome.runtime.sendMessage({
                type: 'GET_COMPLETION',
                current_text: textBeforeCursor,
                language: document.documentElement.lang || 'ru'
            }, response => {
                console.log('[Complete] GET_COMPLETION response:', response);
                if (response && response.success && response.suggestion) {
                    suggestionManager.displaySuggestion(element, response.suggestion);
                } else {
                    suggestionManager.clearSuggestion();
                }
            });
        } else {
            suggestionManager.clearSuggestion();
        }
    }, suggestionManager.DEBOUNCE_DELAY);
});
// --- Конец исправления подсказки ---

// Handle special keys for suggestions
document.addEventListener('keydown', (event) => {
    const element = event.target;
    if (!isValidInputElement(element)) return;

    if (event.key === 'Tab' && !event.shiftKey && suggestionManager.currentSuggestion) {
        event.preventDefault();
        suggestionManager.acceptSuggestion();
    } else if (event.key === 'Escape') {
        // Also hide menu on Escape
        if (editingUI && typeof editingUI.hideFloatingMenu === 'function') {
            editingUI.hideFloatingMenu();
        }
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

// Clean up on page unload
window.addEventListener('unload', () => {
    editingUI.hideFloatingMenu();
});
