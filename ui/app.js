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
    switchMainView('chats');
    if (sidebar && sidebar.classList.contains('collapsed')) {
      sidebar.classList.remove('collapsed');
    }
  } else if (tabName === 'schedules') {
    closeAllModals();
    switchMainView('schedules');
  } else if (tabName === 'alerts') {
    closeAllModals();
    switchMainView('alerts');
  } else if (tabName === 'plugins') {
    closeAllModals();
    switchMainView('plugins');
  } else if (tabName === 'library') {
    closeAllModals();
    switchMainView('library');
  }
}

function switchMainView(viewName) {
  const chatViewport = document.querySelector('.chat-viewport');
  const consoleDock = document.querySelector('.console-dock');
  const schedulesView = document.getElementById('schedules-view');
  const alertsView = document.getElementById('alerts-view');
  const pluginsView = document.getElementById('plugins-view');
  const libraryView = document.getElementById('library-view');

  // Hide all viewports
  if (chatViewport) chatViewport.classList.add('hidden');
  if (consoleDock) consoleDock.classList.add('hidden');
  if (schedulesView) schedulesView.classList.add('hidden');
  if (alertsView) alertsView.classList.add('hidden');
  if (pluginsView) pluginsView.classList.add('hidden');
  if (libraryView) libraryView.classList.add('hidden');

  document.querySelectorAll('.nav-section-btn').forEach(b => b.classList.remove('active'));
  const activeTab = document.getElementById(`tab-btn-${viewName}`);
  if (activeTab) activeTab.classList.add('active');

  if (viewName === 'schedules') {
    if (schedulesView) schedulesView.classList.remove('hidden');
    loadDeadlines();
  } else if (viewName === 'alerts') {
    if (alertsView) alertsView.classList.remove('hidden');
    loadTeamsAlerts();
  } else if (viewName === 'plugins') {
    if (pluginsView) pluginsView.classList.remove('hidden');
    loadPlugins();
  } else if (viewName === 'library') {
    if (libraryView) libraryView.classList.remove('hidden');
    loadLibraryItems();
  } else {
    // Default to chats
    if (chatViewport) chatViewport.classList.remove('hidden');
    if (consoleDock) consoleDock.classList.remove('hidden');
    const chatsTab = document.getElementById('tab-btn-chats');
    if (chatsTab) chatsTab.classList.add('active');
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
    if (modalId === 'alerts-modal') {
      loadTeamsAlerts();
    }
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
// State variables
let projects = [];
let expandedProjects = new Set();
let selectedProjectColor = '#A3E635';
let sessionToDeleteId = null;
let projectToDeleteId = null;
let activeContextMenuSessionId = null;
let activeContextMenuTarget = null; // { sessionId, itemElement, titleSpan }

// Section Collapse States (Accordion / Dropdown Carets)
let isPinnedCollapsed = false;
let isProjectsCollapsed = false;
let isRecentsCollapsed = false;

function togglePinnedSection() {
  isPinnedCollapsed = !isPinnedCollapsed;
  renderSessionsList();
}

function toggleProjectsSection() {
  isProjectsCollapsed = !isProjectsCollapsed;
  renderSessionsList();
}

function toggleRecentsSection() {
  isRecentsCollapsed = !isRecentsCollapsed;
  renderSessionsList();
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.sessions)) {
        sessions = data.sessions.map(s => ({
          id: s.id,
          title: s.title,
          createdAt: s.created_at * 1000,
          metadata: s.metadata || {},
          pinned: !!(s.metadata && s.metadata.pinned),
          projectId: (s.metadata && s.metadata.project_id) || null,
          messages: [],
        }));
        saveSessions();
        if (sessions.length > 0) {
          renderSessionsList();
          if (data.active_session_id && sessions.some(s => s.id === data.active_session_id)) {
            currentSessionId = data.active_session_id;
            await loadSessionMessages(currentSessionId);
          } else {
            currentSessionId = null;
            messagesContainer.innerHTML = '';
            if (welcomeCard) messagesContainer.appendChild(welcomeCard);
          }
        } else {
          currentSessionId = null;
          messagesContainer.innerHTML = '';
          if (welcomeCard) messagesContainer.appendChild(welcomeCard);
          renderSessionsList();
        }
        return;
      }
    }
  } catch (e) {
    console.warn('Backend session fetch failed, falling back to local cache:', e);
  }

  // Fallback to localStorage ONLY if network request failed completely
  try {
    const raw = localStorage.getItem('meera_sessions');
    sessions = raw ? JSON.parse(raw) : [];
  } catch (e) {
    sessions = [];
  }

  currentSessionId = null;
  messagesContainer.innerHTML = '';
  if (welcomeCard) messagesContainer.appendChild(welcomeCard);
  renderSessionsList();
}

function saveSessions() {
  localStorage.setItem('meera_sessions', JSON.stringify(sessions));
}

// ==========================================
// 4b. PROJECTS & FOLDER INTERACTIONS
// ==========================================

async function loadProjects() {
  try {
    const res = await fetch('/api/projects');
    if (res.ok) {
      const data = await res.json();
      projects = data.projects || [];
      // Default: expand all project folders so nested chats are visible
      projects.forEach(p => expandedProjects.add(p.id));
      renderSessionsList();
    }
  } catch (e) {
    console.debug('Failed to load projects:', e);
  }
}

function toggleProjectFolder(projectId) {
  if (expandedProjects.has(projectId)) {
    expandedProjects.delete(projectId);
  } else {
    expandedProjects.add(projectId);
  }
  renderSessionsList();
}

function openCreateProjectModal() {
  const modal = document.getElementById('modal-create-project');
  if (modal) {
    modal.classList.remove('hidden');
    const input = document.getElementById('project-name-input');
    if (input) {
      input.value = '';
      input.focus();
    }
    const desc = document.getElementById('project-desc-input');
    if (desc) desc.value = '';
    selectedProjectColor = '#A3E635';
    document.querySelectorAll('.color-swatch-btn').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-color') === selectedProjectColor);
    });
  }
}

function closeCreateProjectModal() {
  const modal = document.getElementById('modal-create-project');
  if (modal) modal.classList.add('hidden');
}

function selectProjectColor(color, btn) {
  selectedProjectColor = color;
  document.querySelectorAll('.color-swatch-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

async function submitCreateProject() {
  const nameInput = document.getElementById('project-name-input');
  const name = nameInput ? nameInput.value.trim() : '';
  if (!name) return;
  const descInput = document.getElementById('project-desc-input');
  const desc = descInput ? descInput.value.trim() : '';

  try {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        description: desc,
        color: selectedProjectColor,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.project) {
        projects.push(data.project);
        expandedProjects.add(data.project.id);
        renderSessionsList();
      }
    }
  } catch (e) {
    console.warn('Create project failed:', e);
  }

  closeCreateProjectModal();
}

function confirmDeleteProject(projectId, projectName) {
  projectToDeleteId = projectId;
  const modal = document.getElementById('modal-confirm-delete-project');
  const titlePreview = document.getElementById('delete-project-title-preview');
  if (titlePreview) titlePreview.textContent = `'${projectName}'`;
  if (modal) modal.classList.remove('hidden');

  const btnConfirm = document.getElementById('btn-dialog-confirm-delete-project');
  if (btnConfirm) {
    btnConfirm.onclick = async () => {
      await executeDeleteProject(projectToDeleteId);
      closeDeleteProjectConfirmModal();
    };
  }
}

function closeDeleteProjectConfirmModal() {
  const modal = document.getElementById('modal-confirm-delete-project');
  if (modal) modal.classList.add('hidden');
  projectToDeleteId = null;
}

async function executeDeleteProject(projectId) {
  try {
    await fetch(`/api/projects/${projectId}`, { method: 'DELETE' });
    projects = projects.filter(p => p.id !== projectId);
    expandedProjects.delete(projectId);
    sessions.forEach(s => {
      if (s.projectId === projectId) {
        s.projectId = null;
        if (s.metadata) {
          delete s.metadata.project_id;
          delete s.metadata.project_name;
        }
      }
    });
    saveSessions();
    renderSessionsList();
  } catch (e) {
    console.warn('Delete project error:', e);
  }
}

async function createNewSession(customProjectId = null) {
  const targetProjId = customProjectId;
  const proj = projects.find(p => p.id === targetProjId);
  const newId = 'session_' + Date.now();
  const meta = {};
  if (targetProjId) {
    meta.project_id = targetProjId;
    if (proj) meta.project_name = proj.name;
    expandedProjects.add(targetProjId);
  }

  try {
    const res = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: newId,
        title: 'New Conversation',
        metadata: meta,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.session) {
        sessions.unshift({
          id: data.session.id,
          title: data.session.title,
          createdAt: data.session.created_at * 1000,
          metadata: data.session.metadata || meta,
          pinned: false,
          projectId: targetProjId,
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
    metadata: meta,
    pinned: false,
    projectId: targetProjId,
    messages: [],
  };
  sessions.unshift(session);
  currentSessionId = newId;
  saveSessions();
  renderSessionsList();
  loadSessionMessages(newId);
}

function createChatInProject(projectId) {
  expandedProjects.add(projectId);
  createNewSession(projectId);
}

async function togglePinSession(sessionId) {
  const s = sessions.find(item => item.id === sessionId);
  if (!s) return;
  const newPinned = !s.pinned;
  s.pinned = newPinned;
  if (!s.metadata) s.metadata = {};
  s.metadata.pinned = newPinned;

  try {
    await fetch(`/api/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metadata: { pinned: newPinned } }),
    });
  } catch (e) {
    console.warn('Toggle pin session offline:', e);
  }

  saveSessions();
  renderSessionsList();
}

function confirmDeleteSession(sessionId) {
  sessionToDeleteId = sessionId;
  const s = sessions.find(item => item.id === sessionId);
  const title = s ? s.title : 'this conversation';

  const modal = document.getElementById('modal-confirm-delete');
  const preview = document.getElementById('delete-chat-title-preview');
  if (preview) preview.textContent = `'${title}'`;
  if (modal) modal.classList.remove('hidden');

  const btnConfirm = document.getElementById('btn-dialog-confirm-delete');
  if (btnConfirm) {
    btnConfirm.onclick = async () => {
      await executeDeleteSession(sessionToDeleteId);
      closeDeleteConfirmModal();
    };
  }
}

function closeDeleteConfirmModal() {
  const modal = document.getElementById('modal-confirm-delete');
  if (modal) modal.classList.add('hidden');
  sessionToDeleteId = null;
}

async function executeDeleteSession(sessionId) {
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
      fetch('/api/sessions/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSessionId }),
      }).catch(() => {});
      await loadSessionMessages(currentSessionId);
    } else {
      currentSessionId = null;
      fetch('/api/sessions/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: null }),
      }).catch(() => {});
      messagesContainer.innerHTML = '';
      if (welcomeCard) messagesContainer.appendChild(welcomeCard);
    }
  }
  renderSessionsList();
}

// ==========================================
// 4c. CHAT HISTORY RENDERING & CONTEXT MENU
// ==========================================

function renderSessionsList() {
  if (!historyList) return;
  historyList.innerHTML = '';

  const badgeCount = document.getElementById('badge-chat-count');
  if (badgeCount) badgeCount.textContent = sessions.length;

  // 1. PINNED SECTION
  const pinnedSessions = sessions.filter(s => s.pinned);
  if (pinnedSessions.length > 0) {
    const pinnedHeader = document.createElement('div');
    pinnedHeader.className = 'sidebar-section-header';
    pinnedHeader.onclick = togglePinnedSection;
    pinnedHeader.title = isPinnedCollapsed ? 'Expand Pinned' : 'Collapse Pinned';
    pinnedHeader.innerHTML = `
      <span class="sidebar-section-title">
        <span>Pinned</span>
        <svg class="section-chevron ${isPinnedCollapsed ? 'collapsed' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </span>
    `;
    historyList.appendChild(pinnedHeader);

    if (!isPinnedCollapsed) {
      pinnedSessions.forEach(s => {
        historyList.appendChild(createHistoryItemElement(s));
      });
    }
  }

  // 2. PROJECTS SECTION
  const projHeader = document.createElement('div');
  projHeader.className = 'sidebar-section-header';
  projHeader.title = isProjectsCollapsed ? 'Expand Projects' : 'Collapse Projects';
  projHeader.innerHTML = `
    <span class="sidebar-section-title">
      <span>Projects</span>
      <svg class="section-chevron ${isProjectsCollapsed ? 'collapsed' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <polyline points="6 9 12 15 18 9"></polyline>
      </svg>
    </span>
    <button class="btn-proj-action" onclick="event.stopPropagation(); openCreateProjectModal()" title="New Project">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <line x1="12" y1="5" x2="12" y2="19"></line>
        <line x1="5" y1="12" x2="19" y2="12"></line>
      </svg>
    </button>
  `;
  projHeader.onclick = (e) => {
    if (!e.target.closest('.btn-proj-action')) {
      toggleProjectsSection();
    }
  };
  historyList.appendChild(projHeader);

  if (!isProjectsCollapsed) {
    if (projects.length === 0) {
      const emptyProj = document.createElement('div');
      emptyProj.style.padding = '6px 10px';
      emptyProj.style.fontSize = '0.78rem';
      emptyProj.style.color = 'var(--text-dim)';
      emptyProj.textContent = 'No projects yet. Click + to create.';
      historyList.appendChild(emptyProj);
    } else {
      projects.forEach(p => {
        const projContainer = document.createElement('div');
        projContainer.className = 'project-folder-card';

        const isExpanded = expandedProjects.has(p.id);
        const folderRow = document.createElement('div');
        folderRow.className = 'project-folder-row';
        folderRow.onclick = () => toggleProjectFolder(p.id);

        const folderLeft = document.createElement('div');
        folderLeft.className = 'project-folder-left';
        folderLeft.innerHTML = `
          <svg class="project-folder-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <span class="project-folder-title">${escapeHtml(p.name)}</span>
          <svg class="project-folder-chevron ${!isExpanded ? 'collapsed' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        `;

        const folderActions = document.createElement('div');
        folderActions.className = 'project-folder-actions';

        // Prominent + New Chat in Project button
        const addChatBtn = document.createElement('button');
        addChatBtn.className = 'btn-proj-action';
        addChatBtn.title = `New chat in ${p.name}`;
        addChatBtn.innerHTML = `
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        `;
        addChatBtn.onclick = (e) => {
          e.stopPropagation();
          createChatInProject(p.id);
        };

        // Project Dropdown on Hover / Click (···)
        const projOptionsBtn = document.createElement('button');
        projOptionsBtn.className = 'btn-proj-action options';
        projOptionsBtn.title = `Options for ${p.name}`;
        projOptionsBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <circle cx="12" cy="12" r="2"></circle>
            <circle cx="19" cy="12" r="2"></circle>
            <circle cx="5" cy="12" r="2"></circle>
          </svg>
        `;
        projOptionsBtn.onclick = (e) => {
          e.stopPropagation();
          const menu = document.getElementById('project-context-menu');
          const isCurrentOpen = activeProjectMenuId === p.id && menu && !menu.classList.contains('hidden');
          if (isCurrentOpen) {
            closeProjectContextMenu();
          } else {
            openProjectContextMenu(e, p.id, projOptionsBtn, folderRow);
          }
        };

        folderActions.appendChild(addChatBtn);
        folderActions.appendChild(projOptionsBtn);

        folderRow.appendChild(folderLeft);
        folderRow.appendChild(folderActions);
        projContainer.appendChild(folderRow);

        // Render nested chats if folder is expanded
        if (isExpanded) {
          const nestedContainer = document.createElement('div');
          nestedContainer.className = 'project-nested-chats';

          const projChats = sessions.filter(s => !s.pinned && s.projectId === p.id);
          if (projChats.length > 0) {
            projChats.forEach(s => {
              nestedContainer.appendChild(createHistoryItemElement(s, true));
            });
          }
          projContainer.appendChild(nestedContainer);
        }

        historyList.appendChild(projContainer);
      });
    }
  }

  // 3. RECENTS SECTION (Ungrouped & unpinned)
  const recentChats = sessions.filter(s => !s.pinned && (!s.projectId || !projects.some(p => p.id === s.projectId)));
  const recentsHeader = document.createElement('div');
  recentsHeader.className = 'sidebar-section-header';
  recentsHeader.onclick = toggleRecentsSection;
  recentsHeader.title = isRecentsCollapsed ? 'Expand Recents' : 'Collapse Recents';
  recentsHeader.innerHTML = `
    <span class="sidebar-section-title">
      <span>Recents</span>
      <svg class="section-chevron ${isRecentsCollapsed ? 'collapsed' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <polyline points="6 9 12 15 18 9"></polyline>
      </svg>
    </span>
  `;
  historyList.appendChild(recentsHeader);

  if (!isRecentsCollapsed) {
    if (recentChats.length === 0) {
      const emptyRecents = document.createElement('div');
      emptyRecents.style.padding = '6px 10px';
      emptyRecents.style.fontSize = '0.78rem';
      emptyRecents.style.color = 'var(--text-dim)';
      emptyRecents.textContent = 'No recent conversations.';
      historyList.appendChild(emptyRecents);
    } else {
      recentChats.forEach(s => {
        historyList.appendChild(createHistoryItemElement(s, false));
      });
    }
  }
}

function createHistoryItemElement(s, isNested = false) {
  const item = document.createElement('div');
  item.className = `history-item ${s.id === currentSessionId ? 'active' : ''} ${s.pinned ? 'is-pinned' : ''}`;
  item.dataset.sessionId = s.id;

  const titleSpan = document.createElement('span');
  titleSpan.className = 'history-item-title';
  titleSpan.textContent = s.title;
  titleSpan.title = s.title;
  titleSpan.addEventListener('click', () => switchSession(s.id));
  titleSpan.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    startRenameSession(s.id, item, titleSpan);
  });

  const actions = document.createElement('div');
  actions.className = 'history-item-actions';

  // If pinned, show pin marker
  if (s.pinned) {
    const pinBadge = document.createElement('span');
    pinBadge.className = 'pin-status-icon';
    pinBadge.title = 'Pinned conversation';
    pinBadge.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z"></path></svg>`;
    actions.appendChild(pinBadge);
  }

  // Options Button (···) - Click to Open / Toggle
  const optionsBtn = document.createElement('button');
  optionsBtn.className = 'btn-chat-options';
  optionsBtn.title = 'Options';
  optionsBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="2"></circle><circle cx="19" cy="12" r="2"></circle><circle cx="5" cy="12" r="2"></circle></svg>`;
  
  optionsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = document.getElementById('chat-context-menu');
    const isCurrentOpen = activeContextMenuSessionId === s.id && menu && !menu.classList.contains('hidden');
    if (isCurrentOpen) {
      closeContextMenu();
    } else {
      openContextMenu(e, s.id, optionsBtn, item, titleSpan);
    }
  });

  actions.appendChild(optionsBtn);

  item.appendChild(titleSpan);
  item.appendChild(actions);
  return item;
}

// ==========================================
// 4d. FLOATING CONTEXT MENUS (ON CLICK)
// ==========================================

function openContextMenu(e, sessionId, triggerBtn, itemElement, titleSpan) {
  closeContextMenu();
  closeProjectContextMenu();

  activeContextMenuSessionId = sessionId;
  activeContextMenuTarget = { sessionId, itemElement, titleSpan };

  const menu = document.getElementById('chat-context-menu');
  if (!menu) return;

  const session = sessions.find(s => s.id === sessionId);
  if (!session) return;

  // Active button highlight
  triggerBtn.classList.add('active');
  itemElement.classList.add('menu-active');

  // Update Pin label
  const pinLabel = document.getElementById('menu-pin-label');
  if (pinLabel) {
    pinLabel.textContent = session.pinned ? 'Unpin' : 'Pin';
  }

  // Populate Move to project submenu
  populateProjectSubmenu(session);

  // Position context menu directly beside trigger button
  const rect = triggerBtn.getBoundingClientRect();
  menu.classList.remove('hidden');

  const menuWidth = 195;
  const menuHeight = menu.offsetHeight || 180;

  let top = rect.bottom + 4;
  let left = rect.left;

  // Window overflow guards
  if (left + menuWidth > window.innerWidth - 10) {
    left = window.innerWidth - menuWidth - 10;
  }
  if (top + menuHeight > window.innerHeight - 10) {
    top = rect.top - menuHeight - 4;
  }

  menu.style.top = `${Math.max(10, top)}px`;
  menu.style.left = `${Math.max(10, left)}px`;
}

function closeContextMenu() {
  const menu = document.getElementById('chat-context-menu');
  if (menu) menu.classList.add('hidden');
  const submenu = document.getElementById('project-submenu');
  if (submenu) submenu.classList.add('hidden');
  document.querySelectorAll('.history-item.menu-active').forEach(el => el.classList.remove('menu-active'));
  document.querySelectorAll('.btn-chat-options.active').forEach(el => el.classList.remove('active'));
  activeContextMenuSessionId = null;
  activeContextMenuTarget = null;
}

// Project Context Menu
let activeProjectMenuId = null;

function openProjectContextMenu(e, projectId, triggerBtn, folderRow) {
  closeContextMenu();
  closeProjectContextMenu();

  activeProjectMenuId = projectId;
  const menu = document.getElementById('project-context-menu');
  if (!menu) return;

  if (folderRow) folderRow.classList.add('menu-active');
  triggerBtn.classList.add('active');

  const rect = triggerBtn.getBoundingClientRect();
  menu.classList.remove('hidden');

  const menuWidth = 200;
  const menuHeight = menu.offsetHeight || 120;

  let top = rect.bottom + 4;
  let left = rect.left;

  if (left + menuWidth > window.innerWidth - 10) {
    left = window.innerWidth - menuWidth - 10;
  }
  if (top + menuHeight > window.innerHeight - 10) {
    top = rect.top - menuHeight - 4;
  }

  menu.style.top = `${Math.max(10, top)}px`;
  menu.style.left = `${Math.max(10, left)}px`;
}

function closeProjectContextMenu() {
  const menu = document.getElementById('project-context-menu');
  if (menu) menu.classList.add('hidden');
  document.querySelectorAll('.project-folder-row.menu-active').forEach(el => el.classList.remove('menu-active'));
  document.querySelectorAll('.btn-proj-action.options.active').forEach(el => el.classList.remove('active'));
  activeProjectMenuId = null;
}

function populateProjectSubmenu(session) {
  const submenu = document.getElementById('project-submenu');
  if (!submenu) return;
  submenu.innerHTML = '';

  // 1. None / General option
  const noneBtn = document.createElement('button');
  noneBtn.className = `context-submenu-item ${!session.projectId ? 'active' : ''}`;
  noneBtn.innerHTML = `<span>◈</span> <span>General (No project)</span>`;
  noneBtn.onclick = (e) => {
    e.stopPropagation();
    moveSessionToProject(session.id, null);
    closeContextMenu();
  };
  submenu.appendChild(noneBtn);

  // 2. Project options
  projects.forEach(p => {
    const projBtn = document.createElement('button');
    projBtn.className = `context-submenu-item ${session.projectId === p.id ? 'active' : ''}`;
    projBtn.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
      </svg>
      <span>${escapeHtml(p.name)}</span>
    `;
    projBtn.onclick = (e) => {
      e.stopPropagation();
      moveSessionToProject(session.id, p.id);
      closeContextMenu();
    };
    submenu.appendChild(projBtn);
  });

  // 3. New project action
  const divider = document.createElement('div');
  divider.className = 'context-menu-divider';
  submenu.appendChild(divider);

  const newProjBtn = document.createElement('button');
  newProjBtn.className = 'context-submenu-item';
  newProjBtn.innerHTML = `<span>+</span> <span>New Project...</span>`;
  newProjBtn.onclick = (e) => {
    e.stopPropagation();
    closeContextMenu();
    openCreateProjectModal();
  };
  submenu.appendChild(newProjBtn);
}

async function moveSessionToProject(sessionId, targetProjectId) {
  const s = sessions.find(item => item.id === sessionId);
  if (!s) return;

  s.projectId = targetProjectId;
  if (!s.metadata) s.metadata = {};
  if (targetProjectId) {
    s.metadata.project_id = targetProjectId;
    const proj = projects.find(p => p.id === targetProjectId);
    if (proj) s.metadata.project_name = proj.name;
    expandedProjects.add(targetProjectId);
  } else {
    delete s.metadata.project_id;
    delete s.metadata.project_name;
  }

  try {
    await fetch(`/api/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metadata: { project_id: targetProjectId } }),
    });
  } catch (e) {
    console.warn('Move session to project offline:', e);
  }

  saveSessions();
  renderSessionsList();
}

// Attach Context Menu Action Listeners (Chats)
const menuActionRename = document.getElementById('menu-action-rename');
if (menuActionRename) {
  menuActionRename.addEventListener('click', (e) => {
    e.stopPropagation();
    if (activeContextMenuTarget) {
      const { sessionId, itemElement, titleSpan } = activeContextMenuTarget;
      closeContextMenu();
      startRenameSession(sessionId, itemElement, titleSpan);
    }
  });
}

const menuActionPin = document.getElementById('menu-action-pin');
if (menuActionPin) {
  menuActionPin.addEventListener('click', (e) => {
    e.stopPropagation();
    if (activeContextMenuSessionId) {
      const sid = activeContextMenuSessionId;
      closeContextMenu();
      togglePinSession(sid);
    }
  });
}

const menuActionDelete = document.getElementById('menu-action-delete');
if (menuActionDelete) {
  menuActionDelete.addEventListener('click', (e) => {
    e.stopPropagation();
    if (activeContextMenuSessionId) {
      const sid = activeContextMenuSessionId;
      closeContextMenu();
      confirmDeleteSession(sid);
    }
  });
}

const menuMoveWrapper = document.getElementById('menu-move-wrapper');
if (menuMoveWrapper) {
  menuMoveWrapper.addEventListener('mouseenter', () => {
    const submenu = document.getElementById('project-submenu');
    if (submenu) submenu.classList.remove('hidden');
  });
  menuMoveWrapper.addEventListener('mouseleave', () => {
    const submenu = document.getElementById('project-submenu');
    if (submenu) submenu.classList.add('hidden');
  });
}

const menuActionMove = document.getElementById('menu-action-move');
if (menuActionMove) {
  menuActionMove.addEventListener('click', (e) => {
    e.stopPropagation();
    const submenu = document.getElementById('project-submenu');
    if (submenu) submenu.classList.toggle('hidden');
  });
}

// Attach Project Context Menu Listeners
const pmenuActionRename = document.getElementById('pmenu-action-rename');
if (pmenuActionRename) {
  pmenuActionRename.addEventListener('click', (e) => {
    e.stopPropagation();
    if (activeProjectMenuId) {
      const pid = activeProjectMenuId;
      closeProjectContextMenu();
      openRenameProjectModal(pid);
    }
  });
}

const pmenuActionDelete = document.getElementById('pmenu-action-delete');
if (pmenuActionDelete) {
  pmenuActionDelete.addEventListener('click', (e) => {
    e.stopPropagation();
    if (activeProjectMenuId) {
      const pid = activeProjectMenuId;
      closeProjectContextMenu();
      const proj = projects.find(p => p.id === pid);
      confirmDeleteProject(pid, proj ? proj.name : 'this project');
    }
  });
}

let targetRenameProjectId = null;

function openRenameProjectModal(projectId) {
  targetRenameProjectId = projectId;
  const proj = projects.find(p => p.id === projectId);
  const modal = document.getElementById('modal-rename-project');
  const input = document.getElementById('project-rename-input');
  if (input && proj) {
    input.value = proj.name;
    input.focus();
    input.select();
  }
  if (modal) modal.classList.remove('hidden');
}

function closeRenameProjectModal() {
  const modal = document.getElementById('modal-rename-project');
  if (modal) modal.classList.add('hidden');
  targetRenameProjectId = null;
}

async function submitRenameProject() {
  const input = document.getElementById('project-rename-input');
  const newName = input ? input.value.trim() : '';
  if (!newName || !targetRenameProjectId) return;

  const proj = projects.find(p => p.id === targetRenameProjectId);
  if (proj) {
    proj.name = newName;
    try {
      await fetch(`/api/projects/${targetRenameProjectId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName }),
      });
    } catch (e) {
      console.warn('Rename project offline:', e);
    }
    renderSessionsList();
  }
  closeRenameProjectModal();
}

// Close context menus on outside click
document.addEventListener('click', (e) => {
  if (!e.target.closest('#chat-context-menu') &&
      !e.target.closest('#project-context-menu') &&
      !e.target.closest('.btn-chat-options') &&
      !e.target.closest('.btn-proj-action.options')) {
    closeContextMenu();
    closeProjectContextMenu();
  }
});

// Close context menus on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeContextMenu();
    closeProjectContextMenu();
  }
});

function startRenameSession(sessionId, itemElement, titleSpan) {
  const session = sessions.find(s => s.id === sessionId);
  if (!session) return;

  const currentTitle = session.title;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'history-item-rename-input';
  input.value = currentTitle;

  // Replace titleSpan with input element
  itemElement.replaceChild(input, titleSpan);
  input.focus();
  input.select();

  let isCommitted = false;

  const commitRename = async () => {
    if (isCommitted) return;
    isCommitted = true;

    const newTitle = input.value.trim() || currentTitle;
    if (newTitle !== currentTitle) {
      session.title = newTitle;
      saveSessions();
      try {
        await fetch(`/api/sessions/${sessionId}/title`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle }),
        });
      } catch (e) {
        console.warn('Rename session failed on server:', e);
      }
    }
    renderSessionsList();
  };

  const cancelRename = () => {
    if (isCommitted) return;
    isCommitted = true;
    renderSessionsList();
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelRename();
    }
  });

  input.addEventListener('blur', () => {
    commitRename();
  });
}

async function switchSession(sessionId) {
  if (isGenerating || sessionId === currentSessionId) return;
  switchMainView('chats');
  currentSessionId = sessionId;
  fetch('/api/sessions/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {});
  renderSessionsList();
  await loadSessionMessages(sessionId);
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

    // Also update alert count
    const statusRes = await fetch('/api/teams/status');
    if (statusRes.ok) {
      const sData = await statusRes.json();
      const badge = document.getElementById('badge-alert-count');
      if (badge) {
        badge.textContent = sData.unread_alerts || 0;
        if (sData.unread_alerts > 0) {
          badge.classList.add('pulse');
        } else {
          badge.classList.remove('pulse');
        }
      }
    }
  } catch (err) {
    console.debug('Telemetry error:', err);
  }
}

setInterval(updateTelemetry, 4000);
updateTelemetry();

// ==========================================
// 7. SKILLS REGISTRY (PHASE 5)
// ==========================================
let activeSkillId = null;

async function loadSkills() {
  try {
    const res = await fetch('/api/skills');
    if (!res.ok) return;
    const data = await res.json();
    const skills = data.skills || [];
    const active = data.active_skill;
    activeSkillId = active ? active.id : null;

    const container = document.getElementById('skills-modal-body');
    if (!container) return;

    container.innerHTML = '';

    // Baseline item (no specialized prompt)
    const baselineItem = document.createElement('div');
    baselineItem.className = `modal-item clickable ${!activeSkillId ? 'active-skill-item' : ''}`;
    baselineItem.onclick = () => activateSkill('none');
    baselineItem.innerHTML = `
      <div class="item-badge ${!activeSkillId ? 'dot-lime' : ''}"></div>
      <div>
        <div class="item-title">${!activeSkillId ? '◈ ' : ''}Baseline Meera Core</div>
        <div class="item-sub">Zero-token overhead general assistant (unspecialized).</div>
      </div>
    `;
    container.appendChild(baselineItem);

    skills.forEach(s => {
      const isCurrent = s.id === activeSkillId;
      const item = document.createElement('div');
      item.className = `modal-item clickable ${isCurrent ? 'active-skill-item' : ''}`;
      item.onclick = () => activateSkill(isCurrent ? 'none' : s.id);

      let badgeClass = 'dot-lime';
      if (s.id === 'academic') badgeClass = 'dot-iris';
      if (s.id === 'career') badgeClass = 'dot-champagne';

      item.innerHTML = `
        <div class="item-badge ${isCurrent ? badgeClass : ''}"></div>
        <div>
          <div class="item-title">${isCurrent ? '◈ ' : ''}${s.name}</div>
          <div class="item-sub">${s.description}</div>
        </div>
      `;
      container.appendChild(item);
    });
  } catch (err) {
    console.debug('Error loading skills:', err);
  }
}

async function activateSkill(skillId) {
  try {
    const res = await fetch('/api/skills/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_id: skillId })
    });
    if (res.ok) {
      await loadSkills();
    }
  } catch (err) {
    console.error('Error activating skill:', err);
  }
}

// Init Sessions, Projects & Skills
loadProjects();
loadSessions();
loadSkills();
loadDeadlines();
loadPlugins();
loadLibraryItems();
loadTeamsAlerts();

// ==========================================
// 8. SCHEDULES, CALENDAR & ACADEMIC SURFER
// ==========================================
let deadlinesList = [];
let calendarDate = new Date();
let selectedCalDateStr = null;
let currentDeadlinesFilter = 'all';

function filterValidDeadlines(items) {
  let deletedMap = {};
  try {
    deletedMap = JSON.parse(localStorage.getItem('meera_deleted_deadlines') || '{}');
  } catch (_) {}

  const weekAgoDate = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  const todayDate = new Date().toISOString().slice(0, 10);
  const fallCutoff = '2026-08-01';

  return (items || []).filter(d => {
    if (!d.due_date) return false;
    // Check local deleted tombstones
    if (deletedMap[d.id]) return false;
    const dKey = `${(d.title || '').trim().toLowerCase()}_${(d.due_date || '').slice(0, 10)}`;
    if (deletedMap[dKey]) return false;

    // Filter out dates before Fall 2026 or more than 7 days in the past
    if (d.due_date.slice(0, 4) < '2026') return false;
    if (d.due_date.slice(0, 10) < fallCutoff) return false;
    if (d.due_date.slice(0, 10) < weekAgoDate) return false;

    // Drop completed assignments whose due date has already passed
    if (d.is_completed && d.due_date.slice(0, 10) < todayDate) return false;

    // Exclude past semesters and years
    const titleLower = (d.title || '').toLowerCase();
    const groupLower = (d.group_name || '').toLowerCase();
    const pastTerms = ['2023', '2024', '2025', '24-25', '25-26', 'spring 26', 'winter 26', 'even 26', 'spring-26', 'winter-26'];
    if (pastTerms.some(term => titleLower.includes(term) || groupLower.includes(term))) return false;

    return true;
  });
}

async function loadDeadlines() {
  try {
    const res = await fetch('/api/schedules/deadlines');
    if (res.ok) {
      const data = await res.json();
      deadlinesList = filterValidDeadlines(data.deadlines);
      updateDeadlinesBadge();
      renderCalendar();
      renderUpcomingDeadlines();
    }
  } catch (err) {
    console.error('Error fetching academic deadlines:', err);
  }

  // Auto-sync academic deadlines on initial launch if connected
  if (!window._hasAutoSyncedTeamsDeadlines) {
    window._hasAutoSyncedTeamsDeadlines = true;
    fetch('/api/schedules/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
      .then(res => res.json())
      .then(data => {
        if (data && data.synced_count > 0) {
          fetch('/api/schedules/deadlines')
            .then(r => r.json())
            .then(d => {
              if (d.deadlines) {
                deadlinesList = filterValidDeadlines(d.deadlines);
                updateDeadlinesBadge();
                renderCalendar();
                renderUpcomingDeadlines();
              }
            }).catch(() => {});
        }
      })
      .catch(() => {});
  }

  // Check Teams connection state and update banner on Schedules page
  try {
    const tRes = await fetch('/api/teams/status');
    if (tRes.ok) {
      const tData = await tRes.json();
      const notice = document.getElementById('teams-schedules-notice');
      if (notice) {
        if (!tData.connected) {
          notice.classList.remove('hidden');
        } else {
          notice.classList.add('hidden');
        }
      }
    }
  } catch (_) {}
}

function updateDeadlinesBadge() {
  const badge = document.getElementById('badge-deadline-count');
  if (!badge) return;
  const pendingCount = deadlinesList.filter(d => !d.is_completed).length;
  badge.textContent = pendingCount;
}

function renderCalendar() {
  const monthLabel = document.getElementById('calendar-month-label');
  const daysGrid = document.getElementById('calendar-days-grid');
  if (!daysGrid || !monthLabel) return;

  const year = calendarDate.getFullYear();
  const month = calendarDate.getMonth();

  const monthNames = [
    'JANUARY', 'FEBRUARY', 'MARCH', 'APRIL', 'MAY', 'JUNE',
    'JULY', 'AUGUST', 'SEPTEMBER', 'OCTOBER', 'NOVEMBER', 'DECEMBER'
  ];
  monthLabel.textContent = `${monthNames[month]} ${year}`;

  daysGrid.innerHTML = '';

  const firstDay = new Date(year, month, 1);
  let startDayOfWeek = firstDay.getDay();
  let startingIndex = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  // Trailing previous month days
  for (let i = startingIndex - 1; i >= 0; i--) {
    const dayNum = daysInPrevMonth - i;
    const cell = document.createElement('div');
    cell.className = 'calendar-day-cell other-month';
    cell.innerHTML = `<span class="cal-day-num">${dayNum}</span>`;
    daysGrid.appendChild(cell);
  }

  // Current month days
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const cell = document.createElement('div');
    const isToday = dateStr === todayStr;
    const isSelected = dateStr === selectedCalDateStr;

    cell.className = `calendar-day-cell ${isToday ? 'today' : ''} ${isSelected ? 'selected-day' : ''}`;
    cell.onclick = () => selectCalendarDate(dateStr);

    let cellHTML = `<span class="cal-day-num">${day}</span><div class="cal-events-wrap">`;

    const dayDeadlines = deadlinesList.filter(d => (d.due_date || '').startsWith(dateStr));
    const maxChips = 2;
    dayDeadlines.slice(0, maxChips).forEach(d => {
      const platformClass = d.platform === 'teams' ? 'teams' : 'lms';
      const completedClass = d.is_completed ? 'completed' : '';
      cellHTML += `<div class="cal-event-chip ${platformClass} ${completedClass}" title="${escapeHtml(d.title)} [${escapeHtml(d.group_name)}]">${escapeHtml(d.title)}</div>`;
    });

    if (dayDeadlines.length > maxChips) {
      cellHTML += `<div class="cal-more-chip">+${dayDeadlines.length - maxChips} more</div>`;
    }

    cellHTML += `</div>`;
    cell.innerHTML = cellHTML;
    daysGrid.appendChild(cell);
  }

  // Trailing next month days
  const totalCells = startingIndex + daysInMonth;
  const remainingCells = (totalCells <= 35 ? 35 : 42) - totalCells;
  for (let nextDay = 1; nextDay <= remainingCells; nextDay++) {
    const cell = document.createElement('div');
    cell.className = 'calendar-day-cell other-month';
    cell.innerHTML = `<span class="cal-day-num">${nextDay}</span>`;
    daysGrid.appendChild(cell);
  }
}

function navCalendarMonth(direction) {
  calendarDate.setMonth(calendarDate.getMonth() + direction);
  renderCalendar();
}

function navCalendarToday() {
  calendarDate = new Date();
  selectedCalDateStr = null;
  renderCalendar();
  renderUpcomingDeadlines();
}

function selectCalendarDate(dateStr) {
  if (selectedCalDateStr === dateStr) {
    selectedCalDateStr = null;
  } else {
    selectedCalDateStr = dateStr;
  }
  renderCalendar();
  renderUpcomingDeadlines();
}

function filterDeadlines(filterName, btn) {
  currentDeadlinesFilter = filterName;
  document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderUpcomingDeadlines();
}

function renderUpcomingDeadlines() {
  const container = document.getElementById('grouped-deadlines-container');
  const countBadge = document.getElementById('upcoming-total-count');
  if (!container) return;

  let filtered = [...deadlinesList];

  if (selectedCalDateStr) {
    filtered = filtered.filter(d => (d.due_date || '').startsWith(selectedCalDateStr));
  }

  if (currentDeadlinesFilter === 'lms') {
    filtered = filtered.filter(d => d.platform === 'lms');
  } else if (currentDeadlinesFilter === 'teams') {
    filtered = filtered.filter(d => d.platform === 'teams');
  } else if (currentDeadlinesFilter === 'pending') {
    filtered = filtered.filter(d => !d.is_completed);
  } else if (currentDeadlinesFilter === 'completed') {
    filtered = filtered.filter(d => d.is_completed);
  }

  if (countBadge) {
    countBadge.textContent = `${filtered.length} ${filtered.length === 1 ? 'item' : 'items'}`;
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-deadlines-state">
        ◈ No upcoming deadlines matching current filters. Click 'Sync' to explore or configure feeds.
      </div>
    `;
    return;
  }

  const lmsItems = filtered.filter(d => d.platform !== 'teams');
  const teamsItems = filtered.filter(d => d.platform === 'teams');

  let html = '';

  if (lmsItems.length > 0 && currentDeadlinesFilter !== 'teams') {
    html += `
      <div class="deadline-platform-group">
        <div class="platform-group-header lms">
          <span>◈ COURSEWORK &amp; LABS (${lmsItems.length})</span>
          <span>TASKS &amp; MILESTONES</span>
        </div>
        <div class="deadline-cards-list">
          ${lmsItems.map(d => renderDeadlineCard(d)).join('')}
        </div>
      </div>
    `;
  }

  if (teamsItems.length > 0 && currentDeadlinesFilter !== 'lms') {
    html += `
      <div class="deadline-platform-group">
        <div class="platform-group-header teams">
          <span>⬡ ASSIGNMENTS &amp; SCHEDULES (${teamsItems.length})</span>
          <span>TASKS &amp; DELIVERABLES</span>
        </div>
        <div class="deadline-cards-list">
          ${teamsItems.map(d => renderDeadlineCard(d)).join('')}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

function renderDeadlineCard(d) {
  const isCompleted = !!d.is_completed;
  const isUrgent = d.priority === 'urgent' || d.priority === 'high';
  
  let formattedDue = d.due_date;
  try {
    const dt = new Date(d.due_date);
    if (!isNaN(dt.getTime())) {
      const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      const hours = String(dt.getHours()).padStart(2, '0');
      const mins = String(dt.getMinutes()).padStart(2, '0');
      formattedDue = `${monthNames[dt.getMonth()]} ${dt.getDate()}, ${hours}:${mins}`;
    }
  } catch (e) {}

  return `
    <div class="deadline-card ${isCompleted ? 'completed' : ''}" id="card-deadline-${d.id}">
      <input 
        type="checkbox" 
        class="deadline-checkbox" 
        ${isCompleted ? 'checked' : ''} 
        onchange="toggleDeadlineCompleted('${d.id}', this.checked)"
        title="Mark complete / pending"
      />
      <div class="deadline-content">
        <div class="deadline-meta-top">
          <span class="deadline-group-tag">${escapeHtml(d.group_name || (d.platform === 'teams' ? 'Assignments' : 'Coursework'))}</span>
          <span class="deadline-due-badge ${isUrgent ? 'urgent' : ''}">
            ◷ ${escapeHtml(formattedDue)}
          </span>
          ${isUrgent ? '<span class="perm-tag level-act">HIGH PRIORITY</span>' : ''}
        </div>
        <div class="deadline-card-title">${escapeHtml(d.title)}</div>
        ${d.description ? `<div class="deadline-card-desc">${escapeHtml(d.description)}</div>` : ''}
      </div>
      <div class="deadline-card-actions">
        ${d.url ? `<a href="${escapeHtml(d.url)}" target="_blank" class="btn-deadline-action" title="Open Link">↗</a>` : ''}
        <button class="btn-deadline-action delete" onclick="deleteDeadlineItem('${d.id}')" title="Delete Task">×</button>
      </div>
    </div>
  `;
}

async function toggleDeadlineCompleted(deadlineId, isCompleted) {
  try {
    const res = await fetch(`/api/schedules/deadlines/${deadlineId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_completed: isCompleted }),
    });
    if (res.ok) {
      const item = deadlinesList.find(d => d.id === deadlineId);
      if (item) item.is_completed = isCompleted;
      updateDeadlinesBadge();
      renderCalendar();
      renderUpcomingDeadlines();
    }
  } catch (err) {
    console.error('Error toggling deadline:', err);
  }
}

async function deleteDeadlineItem(deadlineId) {
  try {
    // Record into localStorage tombstones immediately so it never resurrects
    const item = deadlinesList.find(d => d.id === deadlineId);
    let deletedMap = {};
    try {
      deletedMap = JSON.parse(localStorage.getItem('meera_deleted_deadlines') || '{}');
    } catch (_) {}
    deletedMap[deadlineId] = Date.now();
    if (item && item.title && item.due_date) {
      const key = `${(item.title || '').trim().toLowerCase()}_${(item.due_date || '').slice(0, 10)}`;
      deletedMap[key] = Date.now();
    }
    localStorage.setItem('meera_deleted_deadlines', JSON.stringify(deletedMap));

    // Remove from in-memory list and immediately update UI
    deadlinesList = deadlinesList.filter(d => d.id !== deadlineId);
    updateDeadlinesBadge();
    renderCalendar();
    renderUpcomingDeadlines();

    // Send delete request to backend
    await fetch(`/api/schedules/deadlines/${encodeURIComponent(deadlineId)}`, {
      method: 'DELETE',
    });
  } catch (err) {
    console.error('Error deleting deadline:', err);
  }
}

async function triggerAcademicSync() {
  const btn = document.getElementById('btn-sync-deadlines');
  const spinner = document.getElementById('sync-spinner');
  const glyph = document.getElementById('sync-glyph');
  const label = document.getElementById('sync-btn-label');
  const banner = document.getElementById('sync-status-banner');
  const bannerText = document.getElementById('sync-status-text');

  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('hidden');
  if (glyph) glyph.classList.add('hidden');
  if (label) label.textContent = 'Surfing Feeds...';

  try {
    const res = await fetch('/api/schedules/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (banner && bannerText) {
      const logs = (data.logs || []).join(' // ');
      if ((data.synced_count || 0) === 0) {
        bannerText.textContent = `◈ Sync completed: 0 upcoming deadlines found. ${logs || 'Ensure account integrations are active.'}`;
      } else {
        bannerText.textContent = `◈ Exploration complete: Synchronized ${data.synced_count} deadlines. ${logs}`;
      }
      banner.classList.remove('hidden');
    }
    await loadDeadlines();
  } catch (err) {
    console.error('Sync failed:', err);
    if (banner && bannerText) {
      bannerText.textContent = `▲ Sync failed: ${err.message || 'Network error'}`;
      banner.classList.remove('hidden');
    }
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add('hidden');
    if (glyph) glyph.classList.remove('hidden');
    if (label) label.textContent = 'Sync';
  }
}

function closeSyncBanner() {
  const banner = document.getElementById('sync-status-banner');
  if (banner) banner.classList.add('hidden');
}

async function openAcademicConfigModal() {
  const modal = document.getElementById('modal-academic-config');
  if (!modal) return;
  modal.classList.remove('hidden');

  try {
    const res = await fetch('/api/schedules/config');
    if (res.ok) {
      const data = await res.json();
      const cfg = data.config || {};
      const lmsUrl = document.getElementById('cfg-lms-url');
      const lmsCookie = document.getElementById('cfg-lms-cookie');
      const teamsUrl = document.getElementById('cfg-teams-url');
      const teamsCookie = document.getElementById('cfg-teams-cookie');
      if (lmsUrl) lmsUrl.value = cfg.lms_feed_url || '';
      if (lmsCookie) lmsCookie.value = cfg.lms_session_cookie || '';
      if (teamsUrl) teamsUrl.value = cfg.teams_feed_url || '';
      if (teamsCookie) teamsCookie.value = cfg.teams_session_cookie || '';
    }
  } catch (e) {
    console.error('Error fetching config:', e);
  }
}

function closeAcademicConfigModal() {
  const modal = document.getElementById('modal-academic-config');
  if (modal) modal.classList.add('hidden');
}

async function saveAcademicConfig() {
  const lmsUrl = document.getElementById('cfg-lms-url')?.value.trim() || '';
  const lmsCookie = document.getElementById('cfg-lms-cookie')?.value.trim() || '';
  const teamsUrl = document.getElementById('cfg-teams-url')?.value.trim() || '';
  const teamsCookie = document.getElementById('cfg-teams-cookie')?.value.trim() || '';

  try {
    const res = await fetch('/api/schedules/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lms_feed_url: lmsUrl,
        lms_session_cookie: lmsCookie,
        teams_feed_url: teamsUrl,
        teams_session_cookie: teamsCookie,
      }),
    });
    if (res.ok) {
      closeAcademicConfigModal();
      triggerAcademicSync();
    }
  } catch (e) {
    console.error('Failed to save academic config:', e);
  }
}

function openAddDeadlineModal() {
  const modal = document.getElementById('modal-add-deadline');
  if (!modal) return;
  modal.classList.remove('hidden');
  const title = document.getElementById('manual-deadline-title');
  if (title) {
    title.value = '';
    title.focus();
  }
  const desc = document.getElementById('manual-deadline-desc');
  if (desc) desc.value = '';
  const group = document.getElementById('manual-deadline-group');
  if (group) group.value = '';
  const due = document.getElementById('manual-deadline-due');
  if (due) {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    due.value = d.toISOString().slice(0, 16);
  }
}

function closeAddDeadlineModal() {
  const modal = document.getElementById('modal-add-deadline');
  if (modal) modal.classList.add('hidden');
}

async function submitAddDeadline() {
  const titleInput = document.getElementById('manual-deadline-title');
  const title = titleInput ? titleInput.value.trim() : '';
  if (!title) return;

  const platform = document.getElementById('manual-deadline-platform')?.value || 'lms';
  const due = document.getElementById('manual-deadline-due')?.value || '';
  const group = document.getElementById('manual-deadline-group')?.value.trim() || 'General';
  const desc = document.getElementById('manual-deadline-desc')?.value.trim() || '';

  try {
    const res = await fetch('/api/schedules/deadlines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        platform,
        due_date: due,
        group_name: group,
        description: desc,
      }),
    });
    if (res.ok) {
      closeAddDeadlineModal();
      await loadDeadlines();
    }
  } catch (err) {
    console.error('Failed to add deadline:', err);
  }
}

// ==========================================
// 9. PLUGINS & INTEGRATION CONNECTORS
// ==========================================
let pluginsList = [];
let activeConfigPluginId = null;

async function loadPlugins() {
  try {
    const res = await fetch('/api/plugins');
    if (res.ok) {
      const data = await res.json();
      pluginsList = data.plugins || [];
      const badge = document.getElementById('badge-plugins-count');
      if (badge) badge.textContent = pluginsList.length;
      renderPluginsList();
    }
  } catch (err) {
    console.error('Error fetching plugins:', err);
  }
}

function renderPluginsList() {
  const container = document.getElementById('plugins-grid');
  if (!container) return;

  container.innerHTML = pluginsList.map(p => {
    let iconGlyph = '◈';
    if (p.id === 'teams') iconGlyph = '⬡';
    if (p.id === 'github') iconGlyph = '⬢';
    if (p.id === 'mcp') iconGlyph = '▲';

    const cfg = p.config || {};
    let isConnected = false;
    if (p.id === 'lms') {
      isConnected = Boolean(cfg.url && (p.status === 'connected' || p.is_enabled));
    } else {
      isConnected = p.status === 'connected';
    }
    let chipsHTML = '';

    if (p.id === 'lms') {
      chipsHTML = `
        <span class="plugin-chip">FEED: ${cfg.url ? 'CONFIGURED' : 'DEFAULT'}</span>
        <span class="plugin-chip">AUTH: ${cfg.cookie ? 'SESSION' : 'TOKEN'}</span>
      `;
    } else if (p.id === 'teams') {
      chipsHTML = `
        <span class="plugin-chip">CALENDAR: ${cfg.url ? 'WEBCAL' : 'DEFAULT'}</span>
        <span class="plugin-chip">TENANT: O365</span>
      `;
    } else if (p.id === 'github') {
      chipsHTML = `
        <span class="plugin-chip">REPO: ${cfg.repo || 'LOCAL'}</span>
        <span class="plugin-chip">MODE: ${cfg.token ? 'AUTHENTICATED' : 'READ'}</span>
      `;
    } else if (p.id === 'mcp') {
      chipsHTML = `
        <span class="plugin-chip">TRANSPORT: STDIO</span>
        <span class="plugin-chip">PROTOCOL: JSON-RPC 2.0</span>
      `;
    }

    return `
      <div class="plugin-card" id="plugin-card-${p.id}">
        <div class="plugin-card-header">
          <div class="plugin-identity">
            <div class="plugin-icon-wrap">${iconGlyph}</div>
            <div>
              <div class="plugin-title">${escapeHtml(p.name)}</div>
              <div class="plugin-category">INTEGRATION // ${p.id.toUpperCase()}</div>
            </div>
          </div>
          <span class="plugin-status-badge ${isConnected ? 'connected' : 'disconnected'}">
            ${isConnected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>

        <div class="plugin-desc">${escapeHtml(p.description)}</div>

        <div class="plugin-details-row">
          ${chipsHTML}
        </div>

        <div class="plugin-card-actions">
          <button class="btn-plugin-action" onclick="testPluginConnection('${p.id}')">Test</button>
          <button class="btn-plugin-action primary" onclick="openPluginConfigModal('${p.id}')">Configure</button>
        </div>
      </div>
    `;
  }).join('');
}

function openPluginConfigModal(pluginId) {
  activeConfigPluginId = pluginId;
  const modal = document.getElementById('modal-plugin-config');
  const title = document.getElementById('plugin-modal-title');
  const body = document.getElementById('plugin-modal-body');
  if (!modal || !body) return;

  const plugin = pluginsList.find(p => p.id === pluginId) || { id: pluginId, name: pluginId.toUpperCase(), config: {} };
  const cfg = plugin.config || {};

  if (title) title.textContent = `⚙ CONFIGURE // ${plugin.name.toUpperCase()}`;

  let formFields = '';
  if (pluginId === 'lms') {
    formFields = `
      <div class="form-group">
        <label class="form-label">COLLEGE LMS CALENDAR / FEED URL</label>
        <input id="pcfg-lms-url" type="text" class="form-input" value="${escapeHtml(cfg.url || '')}" placeholder="https://lms.college.edu/calendar/export_execute.php?..." />
      </div>
      <div class="form-group">
        <label class="form-label">SESSION COOKIE / AUTH HEADER (OPTIONAL)</label>
        <input id="pcfg-lms-cookie" type="text" class="form-input" value="${escapeHtml(cfg.cookie || '')}" placeholder="MoodleSession=... or sessionid=..." />
      </div>
      <div class="form-group">
        <label class="form-label">AUTO-SYNC INTERVAL (MINUTES)</label>
        <input id="pcfg-lms-interval" type="number" class="form-input" value="${cfg.interval || 30}" min="5" max="1440" />
      </div>
    `;
  } else if (pluginId === 'teams') {
    const isConnected = plugin.status === 'connected' || plugin.is_enabled;
    formFields = `
      <div class="devicecode-hero-card">
        <div class="devicecode-title-row">
          <div class="devicecode-title">
            <span>◈</span>
            <span>MICROSOFT DEVICE CODE FLOW (APPROACH 1)</span>
          </div>
          <span class="devicecode-badge ${isConnected ? 'connected' : 'disconnected'}" id="teams-auth-badge">
            ${isConnected ? 'CONNECTED' : 'NOT LINKED'}
          </span>
        </div>
        
        <p style="font-size:0.8rem; color:var(--text-secondary); line-height:1.5;">
          Direct sign-in using your university Microsoft Teams account. 100% free, zero installation, and no web scrapers. Meera will autonomously sync your student assignments and monitor professor announcements across all enrolled class channels.
        </p>

        <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
          <button type="button" class="btn-plugins-primary" id="btn-teams-start-login" onclick="startTeamsDeviceLogin()">
            <span>${isConnected ? 'Re-link Microsoft Account' : 'Link via Microsoft Device Code'}</span>
          </button>
          <button type="button" class="btn-plugin-action" id="btn-teams-sync-now" onclick="syncTeamsNow()" ${!isConnected ? 'disabled style="opacity:0.5;"' : ''}>
            <span>Sync Teams Now</span>
          </button>
        </div>

        <div id="teams-devicecode-card" class="hidden" style="margin-top:10px; display:flex; flex-direction:column; gap:12px;">
          <div class="devicecode-instructions">
            <div class="devicecode-step">
              <span class="step-num">STEP 1:</span>
              <span>Open the Microsoft login page in your browser:</span>
              <a href="https://login.microsoft.com/device" target="_blank" class="btn-open-login" id="teams-login-url-btn">
                <span>Open login.microsoft.com/device ↗</span>
              </a>
            </div>
            <div class="devicecode-step">
              <span class="step-num">STEP 2:</span>
              <span>Copy and enter this 8-character code:</span>
            </div>
          </div>

          <div class="devicecode-box">
            <span class="devicecode-code-display" id="teams-user-code-display">--------</span>
            <button type="button" class="btn-devicecode-copy" onclick="copyTeamsCode()">Copy Code</button>
          </div>

          <div class="devicecode-status-row">
            <span class="pulse-dot"></span>
            <span id="teams-poll-status-text">Waiting for your sign-in in browser...</span>
          </div>
        </div>

        <div id="teams-sync-result-banner" class="hidden" style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:var(--accent-lime); background:rgba(163,230,53,0.1); padding:8px 12px; border-radius:6px; border:1px solid rgba(163,230,53,0.3);">
        </div>
      </div>

      <details style="margin-top:8px;">
        <summary style="font-family:'JetBrains Mono',monospace; font-size:0.72rem; color:var(--text-dim); cursor:pointer;">
          + Alternative: Fallback Webcal Calendar URL &amp; Channel Name
        </summary>
        <div style="margin-top:10px; display:flex; flex-direction:column; gap:10px;">
          <div class="form-group">
            <label class="form-label">MS TEAMS / OUTLOOK WEBCAL URL (FALLBACK)</label>
            <input id="pcfg-teams-url" type="text" class="form-input" value="${escapeHtml(cfg.url || '')}" placeholder="webcal://outlook.office365.com/owa/calendar/..." />
          </div>
          <div class="form-group">
            <label class="form-label">SPECIFIC CHANNEL NAME (OPTIONAL)</label>
            <input id="pcfg-teams-channel" type="text" class="form-input" value="${escapeHtml(cfg.channel || '')}" placeholder="e.g. Operating Systems Lab Channel" />
          </div>
          <div class="form-group">
            <label class="form-label">CUSTOM CLIENT ID (OPTIONAL OVERRIDE)</label>
            <input id="pcfg-teams-client-id" type="text" class="form-input" value="${escapeHtml(cfg.client_id || '')}" placeholder="Leave blank to use default Microsoft CLI App ID" />
          </div>
        </div>
      </details>
    `;
  } else if (pluginId === 'github') {
    formFields = `
      <div class="form-group">
        <label class="form-label">PERSONAL ACCESS TOKEN (PAT)</label>
        <input id="pcfg-github-token" type="password" class="form-input" value="${escapeHtml(cfg.token || '')}" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" />
      </div>
      <div class="form-group">
        <label class="form-label">DEFAULT USERNAME / ORG</label>
        <input id="pcfg-github-user" type="text" class="form-input" value="${escapeHtml(cfg.username || '')}" placeholder="e.g. Arshit-dv" />
      </div>
      <div class="form-group">
        <label class="form-label">REPOSITORIES TO TRACK (COMMA SEPARATED)</label>
        <input id="pcfg-github-repos" type="text" class="form-input" value="${escapeHtml(cfg.repos || '')}" placeholder="e.g. Meera, compiler-lab, os-kernel" />
      </div>
    `;
  } else if (pluginId === 'mcp') {
    formFields = `
      <div class="form-group">
        <label class="form-label">MCP SERVER EXECUTABLE</label>
        <input id="pcfg-mcp-cmd" type="text" class="form-input" value="${escapeHtml(cfg.command || 'npx')}" placeholder="e.g. npx or python" />
      </div>
      <div class="form-group">
        <label class="form-label">ARGUMENTS</label>
        <input id="pcfg-mcp-args" type="text" class="form-input" value="${escapeHtml(cfg.args || '-y @modelcontextprotocol/server-filesystem c:\\workspace')}" placeholder="-y @modelcontextprotocol/server..." />
      </div>
    `;
  }

  body.innerHTML = `
    <p class="modal-dialog-subtext">Settings are persisted locally in SQLite with zero third-party cloud sharing.</p>
    ${formFields}
  `;

  modal.classList.remove('hidden');
}

function closePluginConfigModal() {
  const modal = document.getElementById('modal-plugin-config');
  if (modal) modal.classList.add('hidden');
}

async function submitPluginConfig() {
  if (!activeConfigPluginId) return;

  let cfg = {};
  if (activeConfigPluginId === 'lms') {
    cfg.url = document.getElementById('pcfg-lms-url')?.value.trim() || '';
    cfg.cookie = document.getElementById('pcfg-lms-cookie')?.value.trim() || '';
    cfg.interval = parseInt(document.getElementById('pcfg-lms-interval')?.value || '30', 10);
  } else if (activeConfigPluginId === 'teams') {
    cfg.url = document.getElementById('pcfg-teams-url')?.value.trim() || '';
    cfg.channel = document.getElementById('pcfg-teams-channel')?.value.trim() || '';
    const customCid = document.getElementById('pcfg-teams-client-id')?.value.trim();
    if (customCid) cfg.client_id = customCid;
  } else if (activeConfigPluginId === 'github') {
    cfg.token = document.getElementById('pcfg-github-token')?.value.trim() || '';
    cfg.username = document.getElementById('pcfg-github-user')?.value.trim() || '';
    cfg.repos = document.getElementById('pcfg-github-repos')?.value.trim() || '';
  } else if (activeConfigPluginId === 'mcp') {
    cfg.command = document.getElementById('pcfg-mcp-cmd')?.value.trim() || '';
    cfg.args = document.getElementById('pcfg-mcp-args')?.value.trim() || '';
  }

  try {
    const res = await fetch('/api/plugins/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: activeConfigPluginId,
        is_enabled: true,
        status: 'connected',
        config: cfg,
      }),
    });
    if (res.ok) {
      closePluginConfigModal();
      await loadPlugins();
    }
  } catch (err) {
    console.error('Failed to save plugin config:', err);
  }
}

async function testPluginConnection(pluginId) {
  try {
    const res = await fetch('/api/plugins/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: pluginId }),
    });
    const data = await res.json();
    alert(`[${pluginId.toUpperCase()}] ${data.message || 'Connection Verified'}`);
  } catch (err) {
    alert(`Failed to test ${pluginId}: ${err.message}`);
  }
}

// ==========================================
// 10. LIBRARY & PDF DOCUMENT ARCHIVE
// ==========================================
let libraryItemsList = [];
let currentLibFilterType = 'all';
let librarySearchDebounceTimer = null;
let pendingUploadFile = null;

async function loadLibraryItems(query = '', fileType = 'all') {
  try {
    let url = '/api/library';
    const params = new URLSearchParams();
    if (query) params.append('query', query);
    if (fileType && fileType !== 'all') params.append('file_type', fileType);
    if (params.toString()) url += `?${params.toString()}`;

    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      libraryItemsList = data.items || [];
      const badge = document.getElementById('badge-library-count');
      if (badge) badge.textContent = libraryItemsList.length;
      renderLibraryItems();
    }
  } catch (err) {
    console.error('Error fetching library documents:', err);
  }
}

function renderLibraryItems() {
  const container = document.getElementById('library-items-grid');
  if (!container) return;

  if (libraryItemsList.length === 0) {
    container.innerHTML = `
      <div class="empty-deadlines-state">
        ▤ No documents in Library. Drag and drop your college PDFs, syllabus notes, or lab manuals above.
      </div>
    `;
    return;
  }

  container.innerHTML = libraryItemsList.map(item => {
    let badgeClass = 'other';
    const ext = (item.file_type || '').toLowerCase();
    if (ext === 'pdf') badgeClass = 'pdf';
    else if (ext === 'md' || ext === 'txt') badgeClass = 'md';

    const sizeStr = formatBytes(item.file_size || 0);
    const dateStr = new Date(item.created_at * 1000).toLocaleDateString();

    return `
      <div class="library-card" id="lib-card-${item.id}">
        <div class="library-item-info">
          <div class="file-type-badge ${badgeClass}">${escapeHtml(ext || 'DOC')}</div>
          <div class="library-text-wrap">
            <div class="library-item-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
            <div class="library-meta-row">
              <span>${sizeStr}</span>
              <span>◈ ${dateStr}</span>
              ${item.tags ? `<span class="library-tag-chip">${escapeHtml(item.tags)}</span>` : ''}
            </div>
          </div>
        </div>

        <div class="library-card-actions">
          <button class="btn-lib-action chat" onclick="askMeeraAboutDoc('${escapeHtml(item.title)}', '${item.id}')" title="Ask Meera about this document">
            <span>◈</span>
            <span>Ask</span>
          </button>
          <a href="/api/library/file/${item.id}" target="_blank" class="btn-lib-action" title="Open or download file">
            <span>↗</span>
            <span>Open</span>
          </a>
          <button class="btn-lib-action delete" onclick="deleteLibraryItem('${item.id}')" title="Delete document">
            <span>×</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function filterLibraryType(type, btn) {
  currentLibFilterType = type;
  document.querySelectorAll('.lib-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const searchVal = document.getElementById('library-search-input')?.value.trim() || '';
  loadLibraryItems(searchVal, currentLibFilterType);
}

function debounceLibrarySearch() {
  clearTimeout(librarySearchDebounceTimer);
  librarySearchDebounceTimer = setTimeout(() => {
    const searchVal = document.getElementById('library-search-input')?.value.trim() || '';
    loadLibraryItems(searchVal, currentLibFilterType);
  }, 250);
}

function askMeeraAboutDoc(docTitle, docId) {
  switchMainView('chats');
  insertPrompt(`Analyze and extract key concepts from document: "${docTitle}". Summarize important definitions, lab procedures, and review questions.`);
}

async function deleteLibraryItem(itemId) {
  try {
    const res = await fetch(`/api/library/${itemId}`, { method: 'DELETE' });
    if (res.ok) {
      await loadLibraryItems();
    }
  } catch (err) {
    console.error('Failed to delete library item:', err);
  }
}

// DRAG AND DROP & UPLOAD
const dropzone = document.getElementById('library-dropzone');
if (dropzone) {
  ['dragenter', 'dragover'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });
  dropzone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      uploadFileBlob(files[0]);
    }
  });
}

function handleFileSelect(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    uploadFileBlob(files[0]);
  }
}

function openLibraryUploadModal() {
  pendingUploadFile = null;
  const modal = document.getElementById('modal-library-upload');
  if (!modal) return;
  modal.classList.remove('hidden');
  const title = document.getElementById('upload-doc-title');
  const tags = document.getElementById('upload-doc-tags');
  const desc = document.getElementById('upload-doc-desc');
  const fileInp = document.getElementById('modal-upload-file-input');
  if (title) title.value = '';
  if (tags) tags.value = '';
  if (desc) desc.value = '';
  if (fileInp) fileInp.value = '';
}

function closeLibraryUploadModal() {
  const modal = document.getElementById('modal-library-upload');
  if (modal) modal.classList.add('hidden');
}

function onModalFileChosen(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    pendingUploadFile = files[0];
    const titleInput = document.getElementById('upload-doc-title');
    if (titleInput && !titleInput.value) {
      titleInput.value = files[0].name.replace(/\.[^/.]+$/, '');
    }
  }
}

async function submitLibraryUpload() {
  if (!pendingUploadFile) {
    alert('Please select a file to upload.');
    return;
  }
  const title = document.getElementById('upload-doc-title')?.value.trim() || pendingUploadFile.name;
  const tags = document.getElementById('upload-doc-tags')?.value.trim() || '';
  const desc = document.getElementById('upload-doc-desc')?.value.trim() || '';

  await uploadFileBlob(pendingUploadFile, title, tags, desc);
  closeLibraryUploadModal();
}

function uploadFileBlob(file, customTitle = '', customTags = '', customDesc = '') {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = reader.result;
      try {
        const res = await fetch('/api/library/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: file.name,
            title: customTitle || file.name.replace(/\.[^/.]+$/, ''),
            tags: customTags || '',
            description: customDesc || '',
            content_base64: b64,
          }),
        });
        if (res.ok) {
          await loadLibraryItems();
          resolve();
        } else {
          alert('Upload failed: ' + res.statusText);
          reject();
        }
      } catch (err) {
        alert('Upload error: ' + err.message);
        reject(err);
      }
    };
    reader.readAsDataURL(file);
  });
}

// ==========================================
// 11. TEAMS DEVICE CODE FLOW & ALERTS SENTRY
// ==========================================
let teamsPollingTimer = null;
let currentTeamsUserCode = '';

async function startTeamsDeviceLogin() {
  const card = document.getElementById('teams-devicecode-card');
  const codeDisplay = document.getElementById('teams-user-code-display');
  const statusText = document.getElementById('teams-poll-status-text');
  const btnStart = document.getElementById('btn-teams-start-login');
  const customClientId = document.getElementById('pcfg-teams-client-id')?.value.trim() || undefined;

  if (btnStart) {
    btnStart.disabled = true;
    btnStart.textContent = 'Requesting Code...';
  }

  try {
    const res = await fetch('/api/teams/devicecode/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: customClientId }),
    });
    const data = await res.json();
    if (data.status === 'success') {
      currentTeamsUserCode = data.user_code;
      const vUri = data.verification_uri || 'https://login.microsoft.com/device';
      const loginLink = document.getElementById('teams-login-url-btn');
      if (loginLink) {
        loginLink.href = vUri;
        loginLink.innerHTML = `<span>Open ${vUri.replace('https://', '')} ↗</span>`;
      }
      if (codeDisplay) codeDisplay.textContent = data.user_code;
      if (statusText) statusText.textContent = `Waiting for your sign-in at ${vUri.replace('https://', '')}...`;
      if (card) card.classList.remove('hidden');

      // Attempt to copy code to clipboard automatically
      if (navigator.clipboard && data.user_code) {
        try {
          await navigator.clipboard.writeText(data.user_code.trim());
        } catch (_) {}
      }

      // Start polling
      if (teamsPollingTimer) clearInterval(teamsPollingTimer);
      const intervalSec = data.interval || 5;
      teamsPollingTimer = setInterval(() => {
        pollTeamsDeviceCode(data.device_code);
      }, intervalSec * 1000);
    } else {
      alert(`Error starting login: ${data.error || 'Unknown error'}`);
    }
  } catch (err) {
    console.error('Failed to start device code flow:', err);
    alert('Failed to connect to backend server.');
  } finally {
    if (btnStart) {
      btnStart.disabled = false;
      btnStart.textContent = 'Link via Microsoft Device Code';
    }
  }
}

async function pollTeamsDeviceCode(deviceCode) {
  const statusText = document.getElementById('teams-poll-status-text');
  const badge = document.getElementById('teams-auth-badge');
  const syncBtn = document.getElementById('btn-teams-sync-now');
  const banner = document.getElementById('teams-sync-result-banner');

  try {
    const res = await fetch('/api/teams/devicecode/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_code: deviceCode }),
    });
    const data = await res.json();

    if (data.status === 'authorized') {
      if (teamsPollingTimer) {
        clearInterval(teamsPollingTimer);
        teamsPollingTimer = null;
      }
      if (statusText) statusText.textContent = '◈ Authorization Successful! Connected to Teams.';
      if (badge) {
        badge.textContent = 'CONNECTED';
        badge.className = 'devicecode-badge connected';
      }
      if (syncBtn) {
        syncBtn.disabled = false;
        syncBtn.style.opacity = '1';
      }
      if (banner) {
        banner.textContent = '◈ Successfully linked with Microsoft Teams! Syncing assignments & channel alerts in background...';
        banner.classList.remove('hidden');
      }
      await loadPlugins();
      await loadDeadlines();
      await loadTeamsAlerts();
    } else if (data.status === 'pending') {
      if (statusText) statusText.textContent = data.message || 'Waiting for login in browser...';
    } else if (data.status === 'expired' || data.status === 'error') {
      if (teamsPollingTimer) {
        clearInterval(teamsPollingTimer);
        teamsPollingTimer = null;
      }
      if (statusText) statusText.textContent = `▲ ${data.message || data.error || 'Session ended'}`;
    }
  } catch (err) {
    console.warn('Poll request error:', err);
  }
}

function copyTeamsCode() {
  if (currentTeamsUserCode && navigator.clipboard) {
    navigator.clipboard.writeText(currentTeamsUserCode).then(() => {
      alert(`Copied code: ${currentTeamsUserCode}`);
    });
  }
}

async function refreshAlertsNow(btn) {
  const spinner = document.getElementById('alerts-refresh-spinner');
  const glyph = document.getElementById('alerts-refresh-glyph');
  const label = document.getElementById('alerts-refresh-label');

  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('hidden');
  if (glyph) glyph.classList.add('hidden');
  if (label) label.textContent = 'Scanning...';

  try {
    const res = await fetch('/api/teams/alerts/refresh', { method: 'POST' });
    if (res.ok) {
      await loadTeamsAlerts();
    }
  } catch (err) {
    console.error('Error refreshing alerts:', err);
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add('hidden');
    if (glyph) glyph.classList.remove('hidden');
    if (label) label.textContent = 'Refresh';
  }
}

async function syncTeamsNow() {
  const syncBtn = document.getElementById('btn-teams-sync-now');
  const banner = document.getElementById('teams-sync-result-banner');
  if (syncBtn) {
    syncBtn.disabled = true;
    syncBtn.textContent = 'Syncing...';
  }
  try {
    const res = await fetch('/api/teams/sync', { method: 'POST' });
    const data = await res.json();
    if (banner) {
      banner.textContent = `◈ ${data.message || 'Sync complete.'} (${data.assignments_synced || 0} assignments, ${data.alerts_discovered || 0} alerts)`;
      banner.classList.remove('hidden');
    }
    await loadDeadlines();
    await loadTeamsAlerts();
  } catch (err) {
    if (banner) {
      banner.textContent = `▲ Sync failed: ${err.message}`;
      banner.classList.remove('hidden');
    }
  } finally {
    if (syncBtn) {
      syncBtn.disabled = false;
      syncBtn.textContent = 'Refresh';
    }
  }
}

let currentAlertsList = [];
let currentAlertsFilter = 'all';

async function loadTeamsAlerts() {
  const container = document.getElementById('alerts-modal-body');
  const pageGrid = document.getElementById('alerts-page-grid');
  const badge = document.getElementById('badge-alert-count');
  const pageCountBadge = document.getElementById('alerts-page-total-count');

  try {
    const res = await fetch('/api/teams/alerts');
    if (!res.ok) return;
    const data = await res.json();
    const weekAgoDate = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const weekAgoTs = (Date.now() / 1000) - (7 * 86400);
    currentAlertsList = (data.alerts || []).filter(a => {
      if (!a.timestamp) return false;
      if (a.timestamp.slice(0, 10) < weekAgoDate) return false;
      if (a.timestamp.startsWith('2024') || a.timestamp.startsWith('2025') || a.timestamp.startsWith('2023')) return false;
      const tName = (a.team_name || '').toLowerCase();
      if (tName.includes('24-25') || tName.includes('2024') || tName.includes('23-24')) return false;
      if (a.created_at && a.created_at < weekAgoTs) return false;
      return true;
    });
    const unreadCount = currentAlertsList.filter(a => !a.is_read).length;

    if (badge) {
      badge.textContent = unreadCount;
      if (unreadCount > 0) {
        badge.classList.remove('hidden');
        badge.classList.add('pulse');
      } else {
        badge.classList.remove('pulse');
      }
    }

    if (pageCountBadge) {
      pageCountBadge.textContent = `${currentAlertsList.length} ${currentAlertsList.length === 1 ? 'notice' : 'notices'}`;
    }

    renderAlertsViews();
  } catch (err) {
    console.error('Failed to load alerts:', err);
  }
}

function filterAlerts(filterType, btn) {
  currentAlertsFilter = filterType;
  document.querySelectorAll('.alert-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderAlertsViews();
}

function renderAlertsViews() {
  const modalContainer = document.getElementById('alerts-modal-body');
  const pageContainer = document.getElementById('alerts-page-grid');

  let filtered = [...currentAlertsList];
  if (currentAlertsFilter === 'unread') {
    filtered = filtered.filter(a => !a.is_read);
  }

  const renderCard = (a, isCompact = false) => {
    const isRead = a.is_read;
    const formattedTime = a.timestamp ? a.timestamp.replace('T', ' ').slice(0, 16) : 'Past Week';
    return `
      <div class="alert-card ${isRead ? 'read' : ''}" id="alert-card-${a.id}">
        <div class="alert-card-header">
          <span class="alert-platform-tag">${escapeHtml(a.team_name || 'Course')} // ${escapeHtml(a.channel_name || 'General')}</span>
          <span class="alert-time">${escapeHtml(formattedTime)}</span>
        </div>
        <div class="alert-author-row">
          <span>${escapeHtml(a.author || 'Instructor')}</span>
          <span class="alert-author-team">in ${escapeHtml(a.team_name || 'Class Team')}</span>
        </div>
        <div class="alert-snippet">
          ${escapeHtml(a.snippet || '')}
        </div>
        <div class="alert-card-actions">
          ${!isRead ? `<button class="btn-alert-dismiss" onclick="markAlertRead('${a.id}')">Dismiss / Read</button>` : '<span style="font-size:0.68rem;color:var(--text-dim);">Read</span>'}
          <button class="btn-alert-delete" onclick="deleteAlert('${a.id}')" title="Delete alert permanently">✕ Delete</button>
        </div>
      </div>
    `;
  };

  const emptyHTML = `
    <div class="empty-alerts-state" style="padding:24px; text-align:center; display:flex; flex-direction:column; gap:8px;">
      <div style="font-family:'JetBrains Mono',monospace; color:var(--text-dim); font-size:0.8rem;">
        ◈ ZERO ACTIVE ALERTS (PAST WEEK)
      </div>
      <div style="font-size:0.78rem; color:var(--text-secondary); max-width:400px; margin:0 auto;">
        No notices found in the past 7 days across your course channels. Click 'Refresh' to scan live course channels.
      </div>
    </div>
  `;

  if (modalContainer) {
    modalContainer.innerHTML = filtered.length === 0 ? emptyHTML : filtered.map(a => renderCard(a, true)).join('');
  }

  if (pageContainer) {
    pageContainer.innerHTML = filtered.length === 0 ? emptyHTML : filtered.map(a => renderCard(a, false)).join('');
  }
}

async function markAlertRead(alertId) {
  try {
    await fetch('/api/teams/alerts/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: alertId }),
    });
    await loadTeamsAlerts();
  } catch (err) {
    console.error('Failed to mark alert as read:', err);
  }
}

async function markAllAlertsRead() {
  try {
    await fetch('/api/teams/alerts/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: 'all' }),
    });
    await loadTeamsAlerts();
  } catch (err) {
    console.error('Failed to mark all alerts as read:', err);
  }
}

async function deleteAlert(alertId) {
  try {
    currentAlertsList = currentAlertsList.filter(a => a.id !== alertId);
    renderAlertsViews();
    await fetch(`/api/teams/alerts/${alertId}`, { method: 'DELETE' });
    await loadTeamsAlerts();
  } catch (err) {
    console.error('Failed to delete alert:', err);
  }
}

async function deleteAllAlerts() {
  try {
    currentAlertsList = [];
    renderAlertsViews();
    await fetch('/api/teams/alerts', { method: 'DELETE' });
    await loadTeamsAlerts();
  } catch (err) {
    console.error('Failed to delete all alerts:', err);
  }
}
