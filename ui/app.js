// MEERA — Autonomous Personal AI Agent Studio

const messagesContainer = document.getElementById('messages-container');
const welcomeCard = document.getElementById('welcome-card');
const userInput = document.getElementById('user-input');
const btnSend = document.getElementById('btn-send');
const btnNewSession = document.getElementById('btn-new-session');
const btnCollapseSidebar = document.getElementById('btn-collapse-sidebar');
const btnExpandSidebar = document.getElementById('btn-expand-sidebar');
const sidebar = document.getElementById('sidebar');
const historyList = document.getElementById('history-list');

const iconSend = document.getElementById('icon-send');
const iconLoading = document.getElementById('icon-loading');

const telRam = document.getElementById('tel-ram');
const telModel = document.getElementById('tel-model');
const telEngine = document.getElementById('tel-engine');

let isGenerating = false;
let currentSessionId = null;
let sessions = [];

// ==========================================
// 1. THEME SWITCHER
// ==========================================
function setTheme(themeClass) {
  document.body.className = themeClass;
  localStorage.setItem('meera_theme', themeClass);
  document.querySelectorAll('.mini-swatch').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick')?.includes(themeClass));
  });
}
const savedTheme = localStorage.getItem('meera_theme') || 'theme-graphite-lime';
setTheme(savedTheme);

// ==========================================
// 2. SIDEBAR COLLAPSE / EXPAND & TABS
// ==========================================
function toggleSidebar() {
  if (sidebar) {
    sidebar.classList.toggle('collapsed');
  }
}

if (btnCollapseSidebar) {
  btnCollapseSidebar.addEventListener('click', toggleSidebar);
}
if (btnExpandSidebar) {
  btnExpandSidebar.addEventListener('click', toggleSidebar);
}

// Global Keyboard Shortcut: Ctrl+B or Cmd+B to toggle sidebar, Ctrl+N for new chat
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
    e.preventDefault();
    toggleSidebar();
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault();
    createNewSession();
  }
});

function switchSidebarTab(tabName) {
  document.querySelectorAll('.nav-section-btn').forEach(b => b.classList.remove('active'));
  const target = document.getElementById(`tab-btn-${tabName}`);
  if (target) target.classList.add('active');
  
  if (tabName === 'chats') {
    closeAllModals();
    if (sidebar && sidebar.classList.contains('collapsed')) {
      sidebar.classList.remove('collapsed');
    }
  }
}

// ==========================================
// 3. FLOATING ISLAND DROPDOWN MODALS
// ==========================================
function toggleDropdown(modalId) {
  const target = document.getElementById(modalId);
  if (!target) return;
  const isHidden = target.classList.contains('hidden');
  closeAllModals();
  if (isHidden) {
    target.classList.remove('hidden');
  }
}

function closeAllModals() {
  document.querySelectorAll('.island-modal').forEach(m => m.classList.add('hidden'));
}

// Close modals when clicking outside
document.addEventListener('click', (e) => {
  if (!e.target.closest('.top-floating-island-wrapper')) {
    closeAllModals();
  }
});

// ==========================================
// 4. CHAT SESSIONS & HISTORY (LOCALSTORAGE)
// ==========================================
async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (res.ok) {
      const data = await res.json();
      if (data.sessions && data.sessions.length > 0) {
        sessions = data.sessions.map(s => ({
          id: s.id,
          title: s.title,
          createdAt: s.created_at * 1000,
          messages: [],
        }));
        currentSessionId = data.active_session_id || sessions[0].id;
        saveSessions();
        renderSessionsList();
        await loadSessionMessages(currentSessionId);
        return;
      }
    }
  } catch (e) {
    console.warn('Backend session fetch failed, falling back to local cache:', e);
  }

  // Fallback to localStorage
  try {
    const raw = localStorage.getItem('meera_sessions');
    sessions = raw ? JSON.parse(raw) : [];
  } catch (e) {
    sessions = [];
  }

  if (sessions.length === 0) {
    await createNewSession();
  } else {
    currentSessionId = sessions[0].id;
    renderSessionsList();
    await loadSessionMessages(currentSessionId);
  }
}

function saveSessions() {
  localStorage.setItem('meera_sessions', JSON.stringify(sessions));
}

async function createNewSession() {
  const newId = 'session_' + Date.now();
  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: newId, title: 'New Conversation' }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.session) {
        sessions.unshift({
          id: data.session.id,
          title: data.session.title,
          createdAt: data.session.created_at * 1000,
          messages: [],
        });
        currentSessionId = data.session.id;
        saveSessions();
        renderSessionsList();
        loadSessionMessages(currentSessionId);
        return;
      }
    }
  } catch (e) {
    console.warn('Backend session creation offline:', e);
  }

  const session = {
    id: newId,
    title: 'New Conversation',
    createdAt: Date.now(),
    messages: [],
  };
  sessions.unshift(session);
  currentSessionId = newId;
  saveSessions();
  renderSessionsList();
  loadSessionMessages(newId);
}

function renderSessionsList() {
  if (!historyList) return;
  historyList.innerHTML = '';

  const badgeCount = document.getElementById('badge-chat-count');
  if (badgeCount) badgeCount.textContent = sessions.length;

  sessions.forEach(s => {
    const item = document.createElement('div');
    item.className = `history-item ${s.id === currentSessionId ? 'active' : ''}`;
    
    const titleSpan = document.createElement('span');
    titleSpan.className = 'history-item-title';
    titleSpan.textContent = s.title;
    titleSpan.addEventListener('click', () => switchSession(s.id));

    const delBtn = document.createElement('button');
    delBtn.className = 'history-item-delete';
    delBtn.innerHTML = '&times;';
    delBtn.title = 'Delete chat';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSession(s.id);
    });

    item.appendChild(titleSpan);
    item.appendChild(delBtn);
    historyList.appendChild(item);
  });
}

async function switchSession(sessionId) {
  if (isGenerating || sessionId === currentSessionId) return;
  currentSessionId = sessionId;
  renderSessionsList();
  await loadSessionMessages(sessionId);
}

async function deleteSession(sessionId) {
  try {
    await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  } catch (e) {
    console.warn('Backend delete session error:', e);
  }

  sessions = sessions.filter(s => s.id !== sessionId);
  saveSessions();
  if (currentSessionId === sessionId) {
    if (sessions.length > 0) {
      currentSessionId = sessions[0].id;
      await loadSessionMessages(currentSessionId);
    } else {
      await createNewSession();
    }
  }
  renderSessionsList();
}

async function loadSessionMessages(sessionId) {
  messagesContainer.innerHTML = '';

  try {
    const res = await fetch(`/api/sessions/${sessionId}`);
    if (res.ok) {
      const data = await res.json();
      if (data.session && data.session.title) {
        const local = sessions.find(s => s.id === sessionId);
        if (local) local.title = data.session.title;
        renderSessionsList();
      }
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach(m => {
          appendMessage(m.role, m.content, false);
        });
        return;
      }
    }
  } catch (e) {
    console.warn('Backend loadSessionMessages offline, reading local copy:', e);
  }

  const session = sessions.find(s => s.id === sessionId);
  if (!session || !session.messages || session.messages.length === 0) {
    if (welcomeCard) messagesContainer.appendChild(welcomeCard);
    return;
  }

  session.messages.forEach(m => {
    appendMessage(m.role, m.content, false);
  });
}

btnNewSession.addEventListener('click', createNewSession);

// ==========================================
// 5. INPUT & INFERENCE STREAMING
// ==========================================
userInput.addEventListener('input', () => {
  userInput.style.height = 'auto';
  userInput.style.height = Math.min(userInput.scrollHeight, 160) + 'px';
});

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

btnSend.addEventListener('click', handleSend);

function insertPrompt(text) {
  closeAllModals();
  userInput.value = text;
  userInput.focus();
  userInput.style.height = Math.min(userInput.scrollHeight, 160) + 'px';
}

async function handleSend() {
  const text = userInput.value.trim();
  if (!text || isGenerating) return;

  if (welcomeCard && welcomeCard.parentNode) {
    welcomeCard.remove();
  }

  // Update session title if first message
  let session = sessions.find(s => s.id === currentSessionId);
  if (!session) {
    session = {
      id: 'session_' + Date.now(),
      title: text.length > 28 ? text.slice(0, 28) + '...' : text,
      createdAt: Date.now(),
      messages: [],
    };
    sessions.unshift(session);
    currentSessionId = session.id;
  } else if (session.messages.length === 0) {
    session.title = text.length > 28 ? text.slice(0, 28) + '...' : text;
  }
  saveSessions();
  renderSessionsList();

  appendMessage('user', text, true);
  userInput.value = '';
  userInput.style.height = 'auto';

  const assistantBubble = appendMessage('assistant', '', false);
  setGenerating(true);

  try {
    const response = await fetch('/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: [{ role: 'user', content: text }],
        session_id: currentSessionId,
        stream: true,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let accumulatedText = '';

    let streamDone = false;
    while (!streamDone) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data:')) continue;
        const dataStr = trimmed.slice(5).trim();
        if (dataStr === '[DONE]') {
          streamDone = true;
          break;
        }

        try {
          const parsed = JSON.parse(dataStr);
          const delta = parsed.choices?.[0]?.delta?.content || '';
          if (delta) {
            accumulatedText += delta;
            renderMarkdown(assistantBubble, accumulatedText);
            scrollToBottom();
          }
        } catch (e) {}
      }
    }

    if (!accumulatedText.trim()) {
      assistantBubble.innerHTML = `<span style="color: var(--text-secondary); font-style: italic;">(No output generated from model)</span>`;
    } else {
      renderMarkdown(assistantBubble, accumulatedText);
    }
    scrollToBottom();

    // Persist assistant reply in local session state
    if (session) {
      session.messages.push({ role: 'assistant', content: accumulatedText });
      saveSessions();
    }

    // Refresh session title from backend if available
    try {
      const sRes = await fetch(`/api/sessions/${currentSessionId}`);
      if (sRes.ok) {
        const sData = await sRes.json();
        if (sData.session && sData.session.title) {
          const local = sessions.find(s => s.id === currentSessionId);
          if (local) local.title = sData.session.title;
          renderSessionsList();
        }
      }
    } catch (e) {}

    try { await reader.cancel(); } catch (e) {}
  } catch (err) {
    console.error('Inference error:', err);
    assistantBubble.innerHTML = `<span style="color: #F43F5E;">▲ System Error: ${err.message}. Please verify llama-server process.</span>`;
  } finally {
    setGenerating(false);
    updateTelemetry();
  }
}

function setGenerating(generating) {
  isGenerating = generating;
  btnSend.disabled = generating;
  if (generating) {
    iconSend.classList.add('hidden');
    iconLoading.classList.remove('hidden');
  } else {
    iconSend.classList.remove('hidden');
    iconLoading.classList.add('hidden');
  }
}

function appendMessage(role, rawContent, persist = false) {
  const row = document.createElement('div');
  row.className = `message-row ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = role === 'user' ? 'U' : 'M';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  renderMarkdown(bubble, rawContent);

  row.appendChild(avatar);
  row.appendChild(bubble);
  messagesContainer.appendChild(row);

  if (persist) {
    const session = sessions.find(s => s.id === currentSessionId);
    if (session) {
      session.messages.push({ role, content: rawContent });
      saveSessions();
    }
  }

  scrollToBottom();
  return bubble;
}

function renderMarkdown(element, text) {
  if (!text) {
    element.innerHTML = '<span class="spinner-dock" style="display:inline-block;"></span>';
    return;
  }

  let formatted = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Triple backtick code blocks
  formatted = formatted.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
    return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
  });

  // Inline code
  formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Headers
  formatted = formatted.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  formatted = formatted.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  formatted = formatted.replace(/^# (.*$)/gim, '<h1>$1</h1>');

  // Bold & Italic
  formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Unordered list items (- or *)
  formatted = formatted.replace(/^\s*[-*]\s+(.*$)/gim, '<li>$1</li>');
  formatted = formatted.replace(/(<li>.*<\/li>)/gms, '<ul>$1</ul>');

  // Paragraphs & newlines
  formatted = formatted.replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>');
  element.innerHTML = `<p>${formatted}</p>`;
}

function scrollToBottom() {
  const viewport = document.querySelector('.chat-viewport');
  if (viewport) viewport.scrollTop = viewport.scrollHeight;
}

// ==========================================
// 6. TELEMETRY POLLER
// ==========================================
async function updateTelemetry() {
  try {
    const res = await fetch('/health');
    if (!res.ok) return;
    const data = await res.json();
    const meera = data.meera || {};
    const mm = meera.model_manager || {};
    const provider = mm.provider || {};

    if (telRam) telRam.textContent = `${mm.available_ram_mb || '--'} MB`;
    if (telModel && provider.model) {
      telModel.textContent = provider.model.toUpperCase();
    }

    if (telEngine) {
      if (provider.loaded) {
        telEngine.textContent = 'ACTIVE';
        telEngine.className = 'telemetry-item badge-engine';
      } else {
        telEngine.textContent = 'STANDBY';
        telEngine.className = 'telemetry-item';
      }
    }
  } catch (err) {
    console.debug('Telemetry error:', err);
  }
}

setInterval(updateTelemetry, 4000);
updateTelemetry();

// Init Sessions
loadSessions();
