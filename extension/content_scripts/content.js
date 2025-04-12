console.log("MilashkaAI content script loaded.");

let currentSuggestion = null;
let suggestionElement = null;
let activeInputElement = null; // The input field/textarea currently being used
let debounceTimer = null;
const DEBOUNCE_DELAY = 500; // milliseconds

// --- Completion Logic ---

function getCaretPosition(element) {
    if (element.selectionStart !== undefined) {
        return element.selectionStart;
    }
    // Add fallback for contentEditable if needed
    return -1;
}

function getTextBeforeCaret(element) {
    const position = getCaretPosition(element);
    if (position !== -1) {
        return element.value.substring(0, position);
    }
    // Add fallback for contentEditable if needed
    return "";
}

function insertText(element, textToInsert) {
    const start = element.selectionStart;
    const end = element.selectionEnd;
    const originalText = element.value;
    element.value = originalText.substring(0, start) + textToInsert + originalText.substring(end);
    // Move caret after inserted text
    element.selectionStart = element.selectionEnd = start + textToInsert.length;
    // Trigger input event so frameworks like React/Vue detect the change
    element.dispatchEvent(new Event('input', { bubbles: true }));
}

function displaySuggestion(element, suggestionText) {
    if (!suggestionText) {
        clearSuggestion();
        return;
    }

    // Remove existing suggestion element if any
    clearSuggestion();

    currentSuggestion = suggestionText;
    activeInputElement = element; // Store the element the suggestion is for

    // Create a temporary element to display the suggestion (basic example)
    // This needs significant improvement for robust positioning and styling
    suggestionElement = document.createElement('span');
    suggestionElement.textContent = suggestionText;
    suggestionElement.style.position = 'absolute'; // Or inline relative to caret
    suggestionElement.style.color = 'gray';
    suggestionElement.style.pointerEvents = 'none'; // Don't interfere with clicks
    suggestionElement.classList.add('milashka-suggestion'); // Add class for potential styling

    // --- Basic Positioning (Needs Improvement) ---
    // This is highly dependent on the target input/textarea and page layout.
    // Using a library or more complex calculation is recommended.
    const rect = element.getBoundingClientRect();
    const caretPos = getCaretPosition(element);
    // Rough estimate - needs refinement based on font size, line height etc.
    // For simplicity, just placing it near the element for now.
    suggestionElement.style.left = `${rect.left + window.scrollX + 5}px`; // Adjust based on caret
    suggestionElement.style.top = `${rect.bottom + window.scrollY}px`; // Adjust based on caret line

    document.body.appendChild(suggestionElement);
}

function clearSuggestion() {
    if (suggestionElement) {
        suggestionElement.remove();
        suggestionElement = null;
    }
    currentSuggestion = null;
    // Don't clear activeInputElement here, needed for keydown handling
}

function acceptSuggestion() {
    if (currentSuggestion && activeInputElement) {
        insertText(activeInputElement, currentSuggestion);
        clearSuggestion();
        return true; // Indicate suggestion was accepted
    }
    return false;
}

function handleInput(event) {
    const element = event.target;
    // Check if it's a text input or textarea
    if (element.tagName !== 'INPUT' && element.tagName !== 'TEXTAREA' && !element.isContentEditable) {
        clearSuggestion();
        return;
    }

    activeInputElement = element; // Update active element
    clearSuggestion(); // Clear old suggestion on new input

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        const textBeforeCaret = getTextBeforeCaret(element);
        if (textBeforeCaret && textBeforeCaret.trim().length > 3) { // Only trigger if some text exists
            console.log("Requesting completion for:", textBeforeCaret.slice(-50)); // Log last 50 chars
            chrome.runtime.sendMessage({
                type: "GET_COMPLETION",
                current_text: textBeforeCaret,
                // full_document_context: element.value, // Optional: send full context
                language: document.documentElement.lang || 'ru' // Get page language
            }, (response) => {
                if (chrome.runtime.lastError) {
                    console.error("Completion request error:", chrome.runtime.lastError.message);
                    return;
                }
                if (response && response.success && response.suggestion) {
                    console.log("Received suggestion:", response.suggestion);
                    // Check if the input element is still focused and text hasn't changed drastically
                    if (document.activeElement === element && getTextBeforeCaret(element) === textBeforeCaret) {
                         displaySuggestion(element, response.suggestion);
                    } else {
                        console.log("Context changed, discarding suggestion.");
                    }
                } else if (response && !response.success) {
                    console.error("Completion API error:", response.error);
                }
            });
        }
    }, DEBOUNCE_DELAY);
}

function handleKeyDown(event) {
    if (currentSuggestion && activeInputElement === event.target) {
        if (event.key === 'Enter' || event.key === 'Tab') { // Accept suggestion
            if (acceptSuggestion()) {
                event.preventDefault(); // Prevent default Enter/Tab behavior
            }
        } else if (event.key === 'Escape') { // Reject suggestion
            clearSuggestion();
            event.preventDefault();
        } else {
            // Any other key press likely invalidates the suggestion
            // clearSuggestion(); // Clear immediately or wait for handleInput? Waiting might be better.
        }
    }
    // If no suggestion, let the event bubble up
}

// Attach listeners to the document
document.addEventListener('input', handleInput, true); // Use capture phase for broader coverage
document.addEventListener('keydown', handleKeyDown, true); // Use capture phase
document.addEventListener('focusout', (event) => { // Clear suggestion if element loses focus
    if (event.target === activeInputElement) {
        // Delay clearing slightly in case focus moves to the suggestion UI (if interactive)
        setTimeout(clearSuggestion, 100);
    }
}, true);


// --- Editing Logic ---

let floatingMenu = null;
let currentSelection = null;
let currentSelectionRange = null;

function showFloatingMenu(x, y, selectedText) {
    hideFloatingMenu(); // Remove existing menu

    currentSelection = selectedText;

    floatingMenu = document.createElement('div');
    floatingMenu.className = 'milashka-floating-menu'; // Add class for styling
    floatingMenu.style.position = 'absolute';
    floatingMenu.style.left = `${x}px`;
    floatingMenu.style.top = `${y}px`;
    floatingMenu.style.backgroundColor = 'white';
    floatingMenu.style.border = '1px solid #ccc';
    floatingMenu.style.padding = '8px';
    floatingMenu.style.zIndex = '10001'; // Ensure it's above suggestions

    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Describe edit (or use voice)';
    input.style.marginRight = '5px';

    const voiceButton = document.createElement('button');
    voiceButton.textContent = '🎙️'; // Microphone emoji
    voiceButton.onclick = startVoiceEdit; // Function to handle voice input for editing

    const submitButton = document.createElement('button');
    submitButton.textContent = 'Edit';
    submitButton.onclick = () => {
        const prompt = input.value;
        if (prompt && currentSelection) {
            performEdit(currentSelection, prompt);
        }
        hideFloatingMenu();
    };

    floatingMenu.appendChild(input);
    floatingMenu.appendChild(voiceButton);
    floatingMenu.appendChild(submitButton);

    document.body.appendChild(floatingMenu);

    input.focus();

    // Close menu if clicked outside
    document.addEventListener('mousedown', handleClickOutsideMenu, true);
}

function hideFloatingMenu() {
    if (floatingMenu) {
        floatingMenu.remove();
        floatingMenu = null;
        currentSelection = null;
        currentSelectionRange = null;
        document.removeEventListener('mousedown', handleClickOutsideMenu, true);
    }
}

function handleClickOutsideMenu(event) {
    if (floatingMenu && !floatingMenu.contains(event.target)) {
        hideFloatingMenu();
    }
}

function performEdit(selectedText, prompt) {
    console.log(`Requesting edit for "${selectedText.slice(0, 50)}..." with prompt: "${prompt}"`);
    chrome.runtime.sendMessage({
        type: "EDIT_TEXT",
        selected_text: selectedText,
        prompt: prompt,
        language: document.documentElement.lang || 'ru'
    }, (response) => {
         if (chrome.runtime.lastError) {
            console.error("Edit request error:", chrome.runtime.lastError.message);
            alert(`Edit failed: ${chrome.runtime.lastError.message}`);
            return;
        }
        if (response && response.success && response.edited_text) {
            console.log("Received edited text:", response.edited_text);
            // Replace the original selection with the edited text
            if (currentSelectionRange) {
                // Try to restore selection and replace
                const activeElement = document.activeElement;
                if (activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA')) {
                    const start = currentSelectionRange.startOffset;
                    const end = currentSelectionRange.endOffset;
                    activeElement.setSelectionRange(start, end); // Re-select
                    insertText(activeElement, response.edited_text); // Replace using insertText
                } else if (document.getSelection && currentSelectionRange) {
                    // Fallback for contentEditable or other scenarios
                    const selection = document.getSelection();
                    if (selection.rangeCount > 0) {
                         const range = selection.getRangeAt(0);
                         // Check if the range is still valid (simple check)
                         if (range.toString() === selectedText) {
                            range.deleteContents();
                            range.insertNode(document.createTextNode(response.edited_text));
                         } else {
                             console.warn("Selection changed before edit could be applied.");
                             // Optionally try to insert at original range start/end if possible
                         }
                    }
                }
            } else {
                 console.warn("Could not find original selection range to apply edit.");
                 // Maybe copy to clipboard as a fallback?
                 navigator.clipboard.writeText(response.edited_text).then(() => {
                    alert("Edit complete. Result copied to clipboard as selection could not be restored.");
                 });
            }
        } else if (response && !response.success) {
            console.error("Edit API error:", response.error);
            alert(`Edit failed: ${response.error}`);
        }
    });
}


document.addEventListener('mouseup', (event) => {
    // Don't show menu if clicking inside our own menu
    if (floatingMenu && floatingMenu.contains(event.target)) {
        return;
    }

    const selectedText = window.getSelection().toString().trim();

    if (selectedText.length > 0) {
        // Store the range for later replacement
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
            currentSelectionRange = { // Store basic info, Range object might become invalid
                 startOffset: selection.getRangeAt(0).startOffset,
                 endOffset: selection.getRangeAt(0).endOffset,
                 // Storing parent node info might help restore context later
            };
        } else {
             currentSelectionRange = null;
        }

        // Position menu near the selection end
        const range = window.getSelection().getRangeAt(0);
        const rect = range.getBoundingClientRect();
        showFloatingMenu(event.clientX + window.scrollX, rect.bottom + window.scrollY + 5, selectedText);
    } else {
        // If no text selected, ensure menu is hidden (unless click was inside menu)
        hideFloatingMenu();
    }
});

// Listen for messages from background (e.g., context menu click)
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "SHOW_EDIT_UI") {
    // This might be redundant if mouseup handles it, but good as fallback
    const selectedText = request.selectedText;
     if (selectedText) {
        // Need to get position - context menu doesn't provide coordinates easily
        // For now, just show near top of viewport as placeholder
        showFloatingMenu(10, 10, selectedText);
     }
  }
});


// --- Voice Input Logic ---

let recognition = null;
let isVoiceEdit = false; // Flag to differentiate between general voice input and editing

function setupWebSpeechAPI() {
    window.SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!window.SpeechRecognition) {
        console.error("Web Speech API not supported by this browser.");
        return null;
    }
    const recog = new SpeechRecognition();
    recog.continuous = true; // Keep listening
    recog.interimResults = true; // Get results as they come
    recog.lang = document.documentElement.lang || 'ru-RU'; // Set language

    recog.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
            } else {
                interimTranscript += event.results[i][0].transcript;
            }
        }

        // Display interim results (like suggestion)
        if (interimTranscript && activeInputElement) {
            // TODO: Display interim transcript similar to suggestion
            console.log("Interim:", interimTranscript);
            // displaySuggestion(activeInputElement, interimTranscript); // Reuse suggestion display?
        }

        if (finalTranscript) {
            console.log("Final:", finalTranscript);
            clearSuggestion(); // Clear any interim display
            stopVoiceInput(); // Stop listening after final result

            if (isVoiceEdit && currentSelection) {
                // If editing, use the final transcript as the prompt
                performEdit(currentSelection, finalTranscript);
                hideFloatingMenu();
            } else if (activeInputElement) {
                // If general input, send for formatting and insertion
                sendTranscriptionForFormatting(finalTranscript, recog.lang);
            }
        }
    };

    recog.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        stopVoiceInput(); // Ensure cleanup
        // Provide user feedback
        alert(`Speech recognition error: ${event.error}`);
    };

    recog.onend = () => {
        console.log("Speech recognition ended.");
        // Optionally restart if needed, but for now, stop on end/error
        recognition = null; // Allow starting again
        // Update UI (e.g., button state)
    };

    return recog;
}

function startVoiceInput(forEditing = false) {
    if (recognition) {
        console.log("Recognition already active.");
        return; // Already running
    }
    recognition = setupWebSpeechAPI();
    if (!recognition) return;

    isVoiceEdit = forEditing;
    try {
        recognition.start();
        console.log("Speech recognition started.");
        // Update UI (e.g., indicate recording)
        if (floatingMenu && isVoiceEdit) {
            floatingMenu.querySelector('input').value = "Listening...";
            floatingMenu.querySelector('input').disabled = true;
        }

    } catch (e) {
        console.error("Could not start speech recognition:", e);
        recognition = null;
    }
}

function stopVoiceInput() {
    if (recognition) {
        recognition.stop();
        // Recognition variable is cleared in onend handler
        console.log("Speech recognition stopped.");
         if (floatingMenu && isVoiceEdit) {
            floatingMenu.querySelector('input').value = "";
            floatingMenu.querySelector('input').disabled = false;
        }
    }
}

function startVoiceEdit() {
    startVoiceInput(true); // Start recognition specifically for editing
}

function sendTranscriptionForFormatting(text, lang) {
     console.log("Sending transcription for formatting:", text);
     // This requires audio data, but we only have text from WebSpeech API.
     // We need to decide:
     // 1. Send the TEXT to a different endpoint for formatting ONLY.
     // 2. OR, record audio separately and send to /transcribe endpoint.

     // Option 1: Assume a formatting endpoint exists or adapt the backend.
     // For now, let's just insert the raw text from WebSpeech API as it's simpler
     // and matches the requirement for streaming display (which we haven't fully implemented).
     // A better approach would use the /transcribe endpoint with actual audio for Whisper+Gemma formatting.

     if (activeInputElement) {
         insertText(activeInputElement, text + " "); // Insert final transcript + space
     }

     // --- If sending for formatting (requires backend changes or new endpoint) ---
     /*
     chrome.runtime.sendMessage({
         type: "FORMAT_TEXT_ONLY", // Needs a new message type and handler
         raw_text: text,
         language: lang.split('-')[0] // Extract 'ru' from 'ru-RU'
     }, (response) => {
         if (response && response.success && response.formatted_text) {
             console.log("Received formatted text:", response.formatted_text);
             if (activeInputElement) {
                 // Replace interim/raw text if needed, or just insert
                 insertText(activeInputElement, response.formatted_text + " ");
             }
         } else {
             console.error("Formatting failed:", response?.error);
             // Insert raw text as fallback
             if (activeInputElement) {
                 insertText(activeInputElement, text + " ");
             }
         }
     });
     */
}

// --- Add listener for general voice input trigger (e.g., a button added to the page) ---
// This requires a way to trigger `startVoiceInput(false)` globally. Example:
// document.getElementById('global-voice-button')?.addEventListener('click', () => startVoiceInput(false));