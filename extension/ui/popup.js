document.addEventListener('DOMContentLoaded', () => {
    const uploadForm = document.getElementById('upload-form');
    const fileInput = document.getElementById('file-input');
    const statusDiv = document.getElementById('upload-status');
    const docList = document.getElementById('document-list');

    // --- File Upload ---
    if (uploadForm && fileInput && statusDiv) {
        uploadForm.addEventListener('submit', (event) => {
            event.preventDefault();
            const file = fileInput.files[0];
            if (!file) {
                statusDiv.textContent = 'Please select a file.';
                statusDiv.style.color = 'red';
                return;
            }

            statusDiv.textContent = `Uploading ${file.name}...`;
            statusDiv.style.color = 'black';

            // Read file as ArrayBuffer to send to background script
            const reader = new FileReader();
            reader.onload = (e) => {
                const fileData = e.target.result;
                chrome.runtime.sendMessage({
                    type: "UPLOAD_DOCUMENT",
                    filename: file.name,
                    filetype: file.type,
                    fileData: fileData // Send ArrayBuffer
                }, (response) => {
                     if (chrome.runtime.lastError) {
                        console.error("Upload message error:", chrome.runtime.lastError.message);
                        statusDiv.textContent = `Error: ${chrome.runtime.lastError.message}`;
                        statusDiv.style.color = 'red';
                        return;
                    }
                    if (response && response.success) {
                        statusDiv.textContent = `Upload successful: ${response.metadata.filename} (ID: ${response.metadata.doc_id}). Status: ${response.metadata.status}`;
                        statusDiv.style.color = 'green';
                        // Refresh document list after successful upload
                        loadDocumentList();
                    } else {
                        statusDiv.textContent = `Upload failed: ${response?.error || 'Unknown error'}`;
                        statusDiv.style.color = 'red';
                    }
                });
            };
            reader.onerror = (e) => {
                 statusDiv.textContent = 'Error reading file.';
                 statusDiv.style.color = 'red';
                 console.error("File reading error:", e);
            };
            reader.readAsArrayBuffer(file);
        });
    } else {
        console.error("Could not find upload form elements in popup.html");
    }

    // --- Document List ---
    function loadDocumentList() {
        if (!docList) return;

        docList.innerHTML = '<li>Loading document list...</li>'; // Clear and show loading
        chrome.runtime.sendMessage({ type: "LIST_DOCUMENTS" }, (response) => {
             if (chrome.runtime.lastError) {
                console.error("List documents error:", chrome.runtime.lastError.message);
                docList.innerHTML = `<li>Error loading list: ${chrome.runtime.lastError.message}</li>`;
                return;
            }
            if (response && response.success) {
                docList.innerHTML = ''; // Clear loading message
                if (response.documents && response.documents.length > 0) {
                    response.documents.forEach(doc => {
                        const li = document.createElement('li');
                        li.textContent = `${doc.filename} (Status: ${doc.status || 'unknown'})`;
                        // Add button or link to check status in more detail?
                        docList.appendChild(li);
                    });
                } else {
                    docList.innerHTML = '<li>No documents uploaded yet.</li>';
                }
            } else {
                docList.innerHTML = `<li>Failed to load documents: ${response?.error || 'Unknown error'}</li>`;
            }
        });
    }

    // Load document list when popup opens
    if (docList) {
        loadDocumentList();
    } else {
         console.error("Could not find document list element in popup.html");
    }

});