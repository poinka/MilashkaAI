document.addEventListener('DOMContentLoaded', () => {
    const apiUrlInput = document.getElementById('api-url');
    const saveButton = document.getElementById('save-button');
    const statusDiv = document.getElementById('options-status');

    // Load saved settings
    chrome.storage.sync.get(['apiUrl'], (result) => {
        if (apiUrlInput) {
            apiUrlInput.value = result.apiUrl || 'http://localhost:8000/api/v1'; // Default value
        }
    });

    // Save settings
    if (saveButton && apiUrlInput && statusDiv) {
        saveButton.addEventListener('click', () => {
            const apiUrl = apiUrlInput.value.trim();
            if (apiUrl) {
                chrome.storage.sync.set({ apiUrl: apiUrl }, () => {
                    console.log('API URL saved:', apiUrl);
                    statusDiv.textContent = 'Settings saved!';
                    statusDiv.style.color = 'green';
                    setTimeout(() => { statusDiv.textContent = ''; }, 3000); // Clear status after 3s
                });
            } else {
                 statusDiv.textContent = 'API URL cannot be empty.';
                 statusDiv.style.color = 'red';
            }
        });
    } else {
         console.error("Could not find options page elements.");
    }
});