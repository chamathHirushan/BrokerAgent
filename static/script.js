/**
 * CSE Broker Agent - Chat Interface Script
 */

const chatBox = document.getElementById('chat-box');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const resetBtn = document.getElementById('reset-btn');
const typingIndicator = document.getElementById('typing-indicator');

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

async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    // Add user message
    appendMessage(text, 'user');
    messageInput.value = '';
    messageInput.disabled = true;
    sendBtn.disabled = true;

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