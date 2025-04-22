console.log("MilashkaAI content script loaded.");

class SuggestionManager {
    constructor() {
        this.currentSuggestion = null;
        this.suggestionElement = null;
        this.activeInputElement = null;
        this.debounceTimer = null;
        this.DEBOUNCE_DELAY = 500;
        this.setupMutationObserver();
    }

    setupMutationObserver() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'childList') {
                    this.updateSuggestionPosition();
                }
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    getCaretCoordinates(element, position) {
        const tempSpan = document.createElement('span');
        tempSpan.style.position = 'absolute';
        tempSpan.style.visibility = 'hidden';
        tempSpan.style.whiteSpace = 'pre';
        tempSpan.style.font = window.getComputedStyle(element).font;

        const textBeforeCaret = element.value.substring(0, position);
        tempSpan.textContent = textBeforeCaret;
        document.body.appendChild(tempSpan);

        const rect = element.getBoundingClientRect();
        const spanRect = tempSpan.getBoundingClientRect();

        document.body.removeChild(tempSpan);

        const lineHeight = parseInt(window.getComputedStyle(element).lineHeight);
        const lines = textBeforeCaret.split('\n');
        const currentLine = lines[lines.length - 1];
        const verticalOffset = (lines.length - 1) * lineHeight;

        return {
            left: rect.left + spanRect.width % rect.width,
            top: rect.top + verticalOffset
        };
    }

    displaySuggestion(element, suggestionText) {
        if (!suggestionText) {
            this.clearSuggestion();
            return;
        }

        this.clearSuggestion();

        this.currentSuggestion = suggestionText;
        this.activeInputElement = element;

        this.suggestionElement = document.createElement('div');
        this.suggestionElement.textContent = suggestionText;
        this.suggestionElement.className = 'milashka-suggestion';
        Object.assign(this.suggestionElement.style, {
            position: 'absolute',
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            borderRadius: '2px',
            padding: '2px 4px',
            color: '#666',
            pointerEvents: 'none',
            zIndex: '999999',
            whiteSpace: 'pre-wrap',
            font: window.getComputedStyle(element).font
        });

        document.body.appendChild(this.suggestionElement);
        this.updateSuggestionPosition();

        element.addEventListener('scroll', () => this.updateSuggestionPosition());
        window.addEventListener('scroll', () => this.updateSuggestionPosition());
        window.addEventListener('resize', () => this.updateSuggestionPosition());
    }

    updateSuggestionPosition() {
        if (!this.suggestionElement || !this.activeInputElement) return;

        const coords = this.getCaretCoordinates(
            this.activeInputElement,
            this.activeInputElement.selectionStart
        );

        const scrollX = window.scrollX || window.pageXOffset;
        const scrollY = window.scrollY || window.pageYOffset;

        Object.assign(this.suggestionElement.style, {
            left: `${coords.left + scrollX}px`,
            top: `${coords.top + scrollY}px`
        });
    }

    clearSuggestion() {
        if (this.suggestionElement) {
            this.suggestionElement.remove();
            this.suggestionElement = null;
        }
        this.currentSuggestion = null;
    }

    acceptSuggestion() {
        if (this.currentSuggestion && this.activeInputElement) {
            this.insertText(this.activeInputElement, this.currentSuggestion);
            this.trackSuggestionFeedback(true);
            this.clearSuggestion();
            return true;
        }
        return false;
    }
    
    trackSuggestionFeedback(wasAccepted) {
        if (!this.currentSuggestion) return;
        
        let context = '';
        if (this.activeInputElement && this.activeInputElement.value) {
            const start = Math.max(0, this.activeInputElement.selectionStart - 200);
            const end = Math.min(this.activeInputElement.value.length, this.activeInputElement.selectionStart + 200);
            context = this.activeInputElement.value.substring(start, end);
        }
        
        chrome.runtime.sendMessage({
            type: "TRACK_SUGGESTION",
            suggestion_text: this.currentSuggestion,
            document_context: context,
            was_accepted: wasAccepted,
            source: "completion",
            language: document.documentElement.lang || 'ru'
        }).catch(err => {
            console.error("Failed to track suggestion feedback:", err);
        });
    }

    insertText(element, textToInsert) {
        const start = element.selectionStart;
        const end = element.selectionEnd;
        const originalText = element.value;
        element.value = originalText.substring(0, start) + textToInsert + originalText.substring(end);
        element.selectionStart = element.selectionEnd = start + textToInsert.length;
        element.dispatchEvent(new Event('input', { bubbles: true }));
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

        try {
            const response = await chrome.runtime.sendMessage({
                type: "EDIT_TEXT",
                selected_text: selectedText,
                prompt: prompt,
                language: document.documentElement.lang || 'ru'
            });

            if (response.success) {
                this.applyEdit(response.edited_text, response.confidence);
                if (response.warning) {
                    this.showFeedback(response.warning, 'warning');
                }
            } else {
                throw new Error(response.error);
            }
        } catch (error) {
            this.showFeedback(`Edit failed: ${error.message}`, 'error');
        } finally {
            this.isProcessing = false;
            this.hideFloatingMenu();
        }
    }

    applyEdit(editedText, confidence) {
        const selection = window.getSelection();
        
        if (selection.rangeCount > 0) {
            const range = selection.getRangeAt(0);
            
            const temp = document.createElement('div');
            temp.innerHTML = editedText;
            
            range.deleteContents();
            range.insertNode(temp.firstChild);
            
            if (confidence < 0.7) {
                this.showFeedback(
                    'Low confidence in edit. Please review the changes.',
                    'warning'
                );
            }
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

function handleInput(event) {
    const element = event.target;
    if (!isValidInputElement(element)) {
        suggestionManager.clearSuggestion();
        return;
    }

    suggestionManager.activeInputElement = element;
    suggestionManager.clearSuggestion();

    clearTimeout(suggestionManager.debounceTimer);
    suggestionManager.debounceTimer = setTimeout(() => {
        const textBeforeCaret = element.value.substring(0, element.selectionStart);
        if (textBeforeCaret && textBeforeCaret.trim().length > 3) {
            requestCompletion(textBeforeCaret, element);
        }
    }, suggestionManager.DEBOUNCE_DELAY);
}

function isValidInputElement(element) {
    return element.tagName === 'TEXTAREA' || 
           (element.tagName === 'INPUT' && element.type === 'text') ||
           element.isContentEditable;
}

async function requestCompletion(text, element) {
    try {
        // Check if chrome.runtime is available
        if (!chrome.runtime || !chrome.runtime.sendMessage) {
            console.warn("Extension context may be invalidated, aborting completion request");
            return;
        }

        // Try using the streaming endpoint first
        try {
            console.log("Attempting streaming completion...");
            const streamResponse = await chrome.runtime.sendMessage({
                type: "GET_COMPLETION_STREAM", // Use the streaming endpoint
                current_text: text,
                language: document.documentElement.lang || 'ru'
            }).catch(err => {
                if (err.message.includes("Extension context invalidated")) {
                    console.warn("Extension context was invalidated. Please refresh the page.");
                    throw err; // Re-throw to be caught by outer try/catch
                }
                throw err; // Re-throw any other error
            });
            
            if (streamResponse && streamResponse.success && streamResponse.stream) {
                // Handle the streaming response
                console.log("Using streaming completion");
                let currentSuggestion = "";
                const streamingInterval = setInterval(async () => {
                    try {
                        // Check if element is still active
                        if (document.activeElement !== element) {
                            clearInterval(streamingInterval);
                            if (typeof streamResponse.cancel === 'function') {
                                streamResponse.cancel();
                            } else {
                                console.log("No cancel function available");
                            }
                            return;
                        }
                        
                        // Get next chunk of tokens
                        const chunk = await streamResponse.readNextChunk();
                        
                        if (chunk.done) {
                            clearInterval(streamingInterval);
                            return;
                        }
                        
                        // Process token chunks
                        if (chunk.messages && chunk.messages.length > 0) {
                            // Update with most recent suggestion
                            const lastMessage = chunk.messages[chunk.messages.length - 1];
                            if (lastMessage.suggestion) {
                                currentSuggestion = lastMessage.suggestion;
                                
                                if (document.activeElement === element) {
                                    suggestionManager.displaySuggestion(element, currentSuggestion);
                                }
                            }
                            
                            if (lastMessage.done) {
                                clearInterval(streamingInterval);
                            }
                        }
                    } catch (error) {
                        console.error("Error during stream processing:", error);
                        clearInterval(streamingInterval);
                    }
                }, 100); // Check for new tokens every 100ms
                
                return; // Exit early - we're handling this with streaming
            }
        } catch (streamError) {
            // If streaming fails, fall back to non-streaming endpoint
            console.warn("Streaming completion failed, falling back to standard completion:", streamError);
        }
        
        // Fall back to regular completion if streaming isn't available or failed
        console.log("Falling back to standard completion");
        const response = await chrome.runtime.sendMessage({
            type: "GET_COMPLETION", // Original non-streaming endpoint
            current_text: text,
            language: document.documentElement.lang || 'ru'
        }).catch(err => {
            // Handle potential disconnection errors
            if (err.message.includes("Extension context invalidated")) {
                console.warn("Extension context was invalidated. Please refresh the page.");
                return { success: false, error: "Extension context invalidated" };
            }
            throw err;
        });

        // New error handling: log and return if API error
        if (!response || !response.success) {
            console.error("Completion API error:", response?.error || response);
            return;
        }

        if (response.suggestion) {
            if (document.activeElement === element) {
                suggestionManager.displaySuggestion(element, response.suggestion);
            }
        }
    } catch (error) {
        console.error("Completion request failed. Don't try again immediately if there was an error - that could cause rapid retries", error);
    }
}

document.addEventListener('input', handleInput, true);

document.addEventListener('keydown', (event) => {
    if (suggestionManager.currentSuggestion && 
        suggestionManager.activeInputElement === event.target) {
        if (event.key === 'Tab' || event.key === 'Enter') {
            if (suggestionManager.acceptSuggestion()) {
                event.preventDefault();
            }
        } else if (event.key === 'Escape') {
            suggestionManager.trackSuggestionFeedback(false);
            suggestionManager.clearSuggestion();
            event.preventDefault();
        }
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