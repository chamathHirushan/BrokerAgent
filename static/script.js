/**
 * CSE Broker Agent - Chat Interface Script
 */

const chatBox = document.getElementById('chat-box');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const resetBtn = document.getElementById('reset-btn');
const typingIndicator = document.getElementById('typing-indicator');
const fileUpload = document.getElementById('file-upload');
const fileListContainer = document.getElementById('file-list');

// Store uploaded files to manage state
const uploadedFiles = new Map();

function showTyping() {
    typingIndicator.style.display = 'flex';
    chatBox.scrollTop = chatBox.scrollHeight;
}

function hideTyping() {
    typingIndicator.style.display = 'none';
}

function appendMessage(text, sender) {
    const div = document.createElement('div');
    div.classList.add('message', sender);
    
    // Handle newlines for better formatting
    div.innerHTML = text.replace(/\n/g, '<br>');
    
    // Insert before typing indicator
    chatBox.insertBefore(div, typingIndicator);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function createFileElement(file) {
    const fileId = Math.random().toString(36).substring(7);
    const div = document.createElement('div');
    div.className = 'flex items-center justify-between gap-2 p-3 bg-white rounded-lg border border-gray-200 shadow-sm animate-[fadeIn_0.2s_ease]';
    div.id = `file-${fileId}`;
    
    div.innerHTML = `
        <div class="flex items-center gap-2 overflow-hidden flex-1">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 flex-shrink-0 text-red-500">
                <path fill-rule="evenodd" d="M4.5 2A2.5 2.5 0 002 4.5v11a2.5 2.5 0 002.5 2.5h11a2.5 2.5 0 002.5-2.5v-11A2.5 2.5 0 0015.5 2h-11zm1 2.5a1 1 0 00-1 1v11a1 1 0 001 1h11a1 1 0 001-1v-11a1 1 0 00-1-1h-11zM6.75 9.25a.75.75 0 000 1.5h6.5a.75.75 0 000-1.5h-6.5zm0 3.5a.75.75 0 000 1.5h6.5a.75.75 0 000-1.5h-6.5z" clip-rule="evenodd" />
            </svg>
            <span class="text-sm text-gray-700 truncate font-medium">${file.name}</span>
        </div>
        <div class="flex items-center gap-2">
            <div class="status-indicator text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded self-start">Uploading...</div>
            <button class="delete-btn text-gray-400 hover:text-red-500 transition-colors p-1 rounded-full hover:bg-gray-100 hidden" title="Delete file">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                    <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                </svg>
            </button>
        </div>
    `;

    const deleteBtn = div.querySelector('.delete-btn');
    deleteBtn.addEventListener('click', () => deleteFile(file.name, div));

    fileListContainer.appendChild(div);
    return { element: div, status: div.querySelector('.status-indicator'), deleteBtn };
}

async function uploadFile(file) {
    const ui = createFileElement(file);
    uploadedFiles.set(file.name, ui);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        if (response.ok) {
            ui.status.textContent = "✅";
            ui.status.className = "text-sm";
            ui.status.title = "Uploaded";
            ui.deleteBtn.classList.remove('hidden');
        } else {
            ui.status.textContent = "❌";
            ui.status.className = "text-sm cursor-help";
            ui.status.title = data.error || "Upload failed";
            // Allow deleting failed uploads to clear UI
            ui.deleteBtn.classList.remove('hidden');
        }
    } catch (error) {
        ui.status.textContent = "⚠️";
        ui.status.className = "text-sm cursor-help";
        ui.status.title = error.message;
        ui.deleteBtn.classList.remove('hidden');
    }
}

async function deleteFile(filename, element) {
    const ui = uploadedFiles.get(filename);
    if (ui) {
        ui.status.textContent = "⏳"; // Spinner or hourglass
        ui.deleteBtn.classList.add('hidden');
    }

    try {
        const response = await fetch('/delete_file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: filename })
        });
        
        if (response.ok) {
            console.log(`Deleted ${filename} from Pinecone.`);
            element.remove();
            uploadedFiles.delete(filename);
        } else {
            console.error('Failed to delete file from backend');
            if (ui) {
                ui.status.textContent = "❌";
                ui.deleteBtn.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error deleting file:', error);
        if (ui) {
            ui.status.textContent = "❌";
            ui.deleteBtn.classList.remove('hidden');
        }
    }
}

async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    // Disable inputs
    messageInput.disabled = true;
    sendBtn.disabled = true;

    // Add user message
    appendMessage(text, 'user');
    messageInput.value = '';
    
    // Show typing indicator
    showTyping();

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });
        
        const data = await response.json();
        
        // Hide typing indicator
        hideTyping();

        if (response.ok) {
            appendMessage(data.response, 'agent');
        } else {
            appendMessage('Error: ' + (data.detail || 'Unknown error'), 'agent');
        }
    } catch (error) {
        hideTyping();
        appendMessage('Error: ' + error.message, 'agent');
    } finally {
        messageInput.disabled = false;
        sendBtn.disabled = false;
        messageInput.focus();
    }
}

// Event Listeners
fileUpload.addEventListener('change', async (e) => {
    if (e.target.files.length > 0) {
        const files = Array.from(e.target.files);
        // Clear input so same files can be selected again if needed
        fileUpload.value = '';
        
        // Upload each file
        for (const file of files) {
            // Skip if already uploaded
            if (uploadedFiles.has(file.name)) continue;
            await uploadFile(file);
        }
    }
});

sendBtn.addEventListener('click', sendMessage);

resetBtn.addEventListener('click', async () => {
    if (!confirm('Clear chat history?')) return;
    try {
        await fetch('/reset', { method: 'POST' });
        // Remove all messages except the first greeting
        const messages = chatBox.querySelectorAll('.message');
        for (let i = 1; i < messages.length; i++) {
            messages[i].remove();
        }
    } catch (e) {
        console.error(e);
    }
});

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

// Focus input on load
messageInput.focus();