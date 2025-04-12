// Background service worker for handling API calls, context menus, etc.

// --- Configuration ---
// TODO: Make this configurable via options page
const API_BASE_URL = 'http://localhost:8000/api/v1'; // Default backend URL

// --- Context Menu Setup ---
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "milashkaEdit",
    title: "MilashkaAI Edit...", // Placeholder, might be replaced by floating menu
    contexts: ["selection"]
  });
  console.log("MilashkaAI context menu created.");
});

// Listener for context menu clicks (might be superseded by floating menu in content.js)
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "milashkaEdit" && info.selectionText) {
    // Send message to content script to handle the edit UI
    chrome.tabs.sendMessage(tab.id, {
      type: "SHOW_EDIT_UI",
      selectedText: info.selectionText
    });
  }
});

// --- API Call Functions ---

async function fetchAPI(endpoint, options = {}, isJson = true) {
  const url = `${API_BASE_URL}${endpoint}`;
  console.log(`Fetching API: ${url}`, options);
  try {
    const response = await fetch(url, options);

    if (!response.ok) {
      let errorDetail = `HTTP error! status: ${response.status}`;
      try {
        const errorData = await response.json();
        errorDetail += `, ${JSON.stringify(errorData.detail || errorData)}`;
      } catch (e) { /* Ignore if error response is not JSON */ }
      throw new Error(errorDetail);
    }

    if (isJson) {
      return await response.json();
    } else {
      // For non-JSON responses like file uploads potentially returning metadata
      return response; // Or response.text() if needed
    }
  } catch (error) {
    console.error(`API call failed for ${url}:`, error);
    throw error; // Re-throw to be caught by the caller
  }
}

// --- Message Handling ---
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log("Background received message:", request);

  // Indicate that we will respond asynchronously
  let keepChannelOpen = false;

  if (request.type === "GET_COMPLETION") {
    keepChannelOpen = true;
    fetchAPI('/completion/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_text: request.current_text,
        full_document_context: request.full_document_context,
        language: request.language || 'ru' // Default language
      })
    })
    .then(data => sendResponse({ success: true, suggestion: data.suggestion }))
    .catch(error => sendResponse({ success: false, error: error.message }));

  } else if (request.type === "UPLOAD_DOCUMENT") {
    keepChannelOpen = true;
    const formData = new FormData();
    // The file object needs to be reconstructed if sent from content/popup script
    // Assuming request.fileData contains necessary info (like ArrayBuffer, name, type)
    // This part is tricky and might need adjustment based on how file is sent
    if (request.fileData && request.filename && request.filetype) {
       const blob = new Blob([request.fileData], { type: request.filetype });
       formData.append('file', blob, request.filename);

       fetchAPI('/documents/upload', {
         method: 'POST',
         body: formData
         // Content-Type is set automatically by fetch for FormData
       }, false) // Expecting metadata response, maybe JSON
       .then(response => response.json()) // Now parse JSON
       .then(data => sendResponse({ success: true, metadata: data }))
       .catch(error => sendResponse({ success: false, error: error.message }));
    } else {
        sendResponse({ success: false, error: "Missing file data for upload." });
    }


  } else if (request.type === "TRANSCRIBE_AUDIO") {
    keepChannelOpen = true;
    const formData = new FormData();
    // Assuming request.audioData is ArrayBuffer or similar
    const blob = new Blob([request.audioData], { type: request.audioType || 'audio/webm' }); // Adjust type if needed
    formData.append('audio_file', blob, 'recording.webm'); // Filename might not matter much here
    formData.append('language', request.language || 'ru');

    fetchAPI('/voice/transcribe', {
      method: 'POST',
      body: formData
    })
    .then(data => sendResponse({ success: true, transcription: data }))
    .catch(error => sendResponse({ success: false, error: error.message }));

  } else if (request.type === "VOICE_TO_REQUIREMENT") {
     keepChannelOpen = true;
     const formData = new FormData();
     const blob = new Blob([request.audioData], { type: request.audioType || 'audio/webm' });
     formData.append('audio_file', blob, 'requirement_audio.webm');
     formData.append('language', request.language || 'ru');

     fetchAPI('/voice/to-requirement', {
       method: 'POST',
       body: formData
     })
     .then(data => sendResponse({ success: true, result: data }))
     .catch(error => sendResponse({ success: false, error: error.message }));

  } else if (request.type === "EDIT_TEXT") {
    keepChannelOpen = true;
    fetchAPI('/editing/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_text: request.selected_text,
        prompt: request.prompt,
        language: request.language || 'ru'
      })
    })
    .then(data => sendResponse({ success: true, edited_text: data.edited_text }))
    .catch(error => sendResponse({ success: false, error: error.message }));

  } else if (request.type === "GET_DOCUMENT_STATUS") {
      keepChannelOpen = true;
      fetchAPI(`/documents/status/${request.doc_id}`, { method: 'GET' })
          .then(data => sendResponse({ success: true, status: data }))
          .catch(error => sendResponse({ success: false, error: error.message }));

  } else if (request.type === "LIST_DOCUMENTS") {
      keepChannelOpen = true;
      fetchAPI('/documents/', { method: 'GET' })
          .then(data => sendResponse({ success: true, documents: data }))
          .catch(error => sendResponse({ success: false, error: error.message }));
  }

  // Return true to keep the message channel open for asynchronous responses
  return keepChannelOpen;
});

console.log("MilashkaAI background script loaded.");
