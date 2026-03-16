// ==========================================================================
// CAD Diagram Analyzer — Frontend App Logic
// ==========================================================================

const API = ''; // change to e.g. "http://localhost:8080" if opening as file://

// ==========================================================================
// DOM References
// ==========================================================================

// Workspace wrapper
const workspace = document.getElementById('workspace');

// Input card
const dropZone      = document.getElementById('drop-zone');
const fileInput     = document.getElementById('file-input');
const previewWrap   = document.getElementById('preview-wrap');
const previewImg    = document.getElementById('preview-img');
const previewName   = document.getElementById('preview-name');
const clearBtn      = document.getElementById('clear-btn');
const queryTA       = document.getElementById('query');
const analyzeBtn    = document.getElementById('analyze-btn');
const statusEl      = document.getElementById('status');
const statusText    = document.getElementById('status-text');

// Results / chat panel
const resultsCard   = document.getElementById('results-card');
const chatHistory   = document.getElementById('chat-history');

// Follow-up
const followupSection = document.getElementById('followup-section');
const followupQuery   = document.getElementById('followup-query');
const followupBtn     = document.getElementById('followup-btn');

// Toast container
const toastContainer = document.getElementById('toast-container');

// Pipeline badges
const pipelineLiveBadge    = document.getElementById('pipeline-live-badge');
const pipelineCompleteBadge = document.getElementById('pipeline-complete-badge');

// Pipeline phase elements
const phaseUpload     = document.getElementById('phase-upload');
const phasePreprocess = document.getElementById('phase-preprocess');
const phaseAnalyze    = document.getElementById('phase-analyze');
const phaseResults    = document.getElementById('phase-results');

// Connector elements
const conn12 = document.getElementById('conn-12');
const conn23 = document.getElementById('conn-23');
const conn34 = document.getElementById('conn-34');

// ==========================================================================
// State
// ==========================================================================

let selectedFile      = null;
let currentDiagramId  = null;
let isWorkspaceActive = false;
let isRunning         = false;
let conversationHistory = [];  // [{question, text, toolCalls}]
let _subMsgTimers = {};

// ==========================================================================
// Initialization
// ==========================================================================

function init() {
  setupDragAndDrop();
  setupFileInput();
  setupActions();
  setupFollowup();
  setupImagePanZoom();
}

function setupDragAndDrop() {
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
    dropZone.addEventListener(evt, e => { e.preventDefault(); e.stopPropagation(); });
    document.body.addEventListener(evt, e => { e.preventDefault(); e.stopPropagation(); });
  });

  ['dragenter', 'dragover'].forEach(evt =>
    dropZone.addEventListener(evt, () => dropZone.classList.add('drag-over'))
  );

  ['dragleave', 'drop'].forEach(evt =>
    dropZone.addEventListener(evt, () => dropZone.classList.remove('drag-over'))
  );

  dropZone.addEventListener('drop', e => {
    const files = e.dataTransfer.files;
    if (files.length > 0) handleFile(files[0]);
  });
}

function setupFileInput() {
  fileInput.addEventListener('change', function () {
    if (this.files && this.files.length > 0) handleFile(this.files[0]);
  });
}

function setupActions() {
  clearBtn.addEventListener('click', clearAll);

  analyzeBtn.addEventListener('click', () => {
    runAnalysis(queryTA.value.trim(), false);
  });

  queryTA.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = this.scrollHeight + 'px';
  });
}

function setupFollowup() {
  // Enable send button only when textarea has text
  followupQuery.addEventListener('input', function () {
    // Auto-resize
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 160) + 'px';
    // Enable/disable button
    followupBtn.disabled = !this.value.trim() || isRunning;
  });

  // Enter sends, Shift+Enter adds newline
  followupQuery.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!followupBtn.disabled) {
        runAnalysis(followupQuery.value.trim(), true);
      }
    }
  });

  followupBtn.addEventListener('click', () => {
    runAnalysis(followupQuery.value.trim(), true);
  });
}

// ==========================================================================
// File Handling
// ==========================================================================

function handleFile(file) {
  const validTypes = ['image/jpeg', 'image/png', 'image/tiff', 'image/tif'];
  const ext = file.name.split('.').pop().toLowerCase();
  const validExts = ['jpg', 'jpeg', 'png', 'tif', 'tiff'];

  if (!validTypes.includes(file.type) && !validExts.includes(ext)) {
    showToast('Please upload a valid image file (PNG, JPEG, TIFF).', 'warning');
    return;
  }

  selectedFile = file;

  const reader = new FileReader();
  reader.readAsDataURL(file);
  reader.onloadend = () => {
    previewImg.src = reader.result;
    const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
    previewName.textContent = `${file.name} (${sizeMB} MB)`;

    dropZone.classList.add('hidden');
    previewWrap.classList.remove('hidden');
    analyzeBtn.disabled = false;

    // Reset if a brand-new file is picked mid-session
    if (isWorkspaceActive) {
      // Keep workspace up but reset the conversation
      clearConversation();
      currentDiagramId = null;
    } else {
      resultsCard.classList.add('hidden');
      currentDiagramId = null;
    }
  };
}

function clearAll() {
  selectedFile    = null;
  currentDiagramId = null;
  fileInput.value  = '';

  // Reset workspace
  isWorkspaceActive = false;
  workspace.classList.remove('workspace-active');
  document.querySelector('.container').classList.remove('workspace-active');

  previewWrap.classList.add('hidden');
  dropZone.classList.remove('hidden');
  analyzeBtn.disabled = true;
  resultsCard.classList.add('hidden');

  clearConversation();

  // Reset zoom
  scale = 1; panX = 0; panY = 0;
  updateTransform();
}

function clearConversation() {
  conversationHistory = [];
  chatHistory.innerHTML = '';
  followupSection.classList.add('hidden');
  followupQuery.value = '';
  followupQuery.style.height = '';
  followupBtn.disabled = true;
  resetPipeline();
}

// ==========================================================================
// Image Pan & Zoom
// ==========================================================================

let scale = 1, panX = 0, panY = 0;
let isPanning = false, startX = 0, startY = 0;
const previewViewport = document.getElementById('preview-viewport');

function setupImagePanZoom() {
  if (!previewViewport) return;

  previewViewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = previewViewport.getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;
    const newScale = Math.max(0.15, Math.min(scale + e.deltaY * -0.002, 15));
    if (newScale !== scale) {
      panX = cursorX - (cursorX - panX) * (newScale / scale);
      panY = cursorY - (cursorY - panY) * (newScale / scale);
      scale = newScale;
      updateTransform();
    }
  }, { passive: false });

  previewViewport.addEventListener('mousedown', (e) => {
    isPanning = true;
    startX = e.clientX - panX;
    startY = e.clientY - panY;
    previewViewport.style.cursor = 'grabbing';
  });

  document.addEventListener('mousemove', (e) => {
    if (!isPanning) return;
    panX = e.clientX - startX;
    panY = e.clientY - startY;
    previewImg.style.transition = 'none';
    updateTransform();
  });

  document.addEventListener('mouseup', () => {
    if (isPanning) {
      isPanning = false;
      previewViewport.style.cursor = 'grab';
      previewImg.style.transition = '';
    }
  });

  // Double-click: fit image in viewport
  previewViewport.addEventListener('dblclick', fitImage);

  // Auto-fit when image loads
  previewImg.addEventListener('load', () => {
    scale = 1; panX = 0; panY = 0;
    requestAnimationFrame(fitImage);
  });
}

function fitImage() {
  if (!previewImg.naturalWidth || !previewImg.naturalHeight) return;
  const vw = previewViewport.clientWidth;
  const vh = previewViewport.clientHeight;
  const imgRatio  = previewImg.naturalWidth / previewImg.naturalHeight;
  const viewRatio = vw / vh;

  if (imgRatio > viewRatio) {
    scale = vw / previewImg.naturalWidth;
    panX  = 0;
    panY  = (vh - previewImg.naturalHeight * scale) / 2;
  } else {
    scale = vh / previewImg.naturalHeight;
    panX  = (vw - previewImg.naturalWidth * scale) / 2;
    panY  = 0;
  }
  updateTransform();
}

function updateTransform() {
  previewImg.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
}

// ==========================================================================
// API Calls
// ==========================================================================

async function ingestDiagram(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API}/ingest`, { method: 'POST', body: formData });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Ingestion error (${res.status}): ${txt}`);
  }
  const data = await res.json();
  if (!data.success) throw new Error(data.error_message || 'Ingestion failed on server.');
  return data.diagram_id;
}

async function analyzeQuery(diagramId, query) {
  const res = await fetch(`${API}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ diagram_id: diagramId, query, user_id: 'web-ui-user' }),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`Analysis error (${res.status}): ${txt}`);
  }
  const data = await res.json();
  return { text: data.response, toolCalls: data.tool_calls || [] };
}

// ==========================================================================
// Main Analysis Flow
// ==========================================================================

const SUB_MESSAGES = {
  preprocess: [
    'Sending to Document AI…',
    'Extracting text labels…',
    'Running symbol detection…',
    'Building tile pyramid…',
    'Indexing metadata…',
  ],
  analyze: [
    'Initializing ADK agent…',
    'Calling get_overview…',
    'Inspecting zones…',
    'Searching text labels…',
    'Tracing connections…',
    'Synthesizing response…',
  ],
};

/**
 * Run an analysis pass.
 * @param {string}  queryText   - The question to ask.
 * @param {boolean} isFollowup  - true when diagram is already ingested.
 */
async function runAnalysis(queryText, isFollowup = false) {
  if (!selectedFile && !currentDiagramId) return;

  queryText = (queryText || '').trim();
  if (!queryText) {
    const ta = isFollowup ? followupQuery : queryTA;
    ta.style.boxShadow = '0 0 0 2px var(--error)';
    setTimeout(() => { ta.style.boxShadow = ''; }, 1200);
    ta.focus();
    return;
  }

  isRunning = true;
  followupBtn.disabled = true;
  followupQuery.disabled = true;
  analyzeBtn.disabled = true;
  analyzeBtn.querySelector('span').textContent = 'Processing…';

  // Reset pipeline phases for this run
  resetPipeline();

  // Show the results panel and activate two-column layout on first run
  resultsCard.classList.remove('hidden');
  if (!isWorkspaceActive) {
    activateWorkspace();
  }

  pipelineLiveBadge.classList.remove('hidden');
  pipelineCompleteBadge.classList.add('hidden');

  // Scroll to results panel
  setTimeout(() => resultsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 80);

  const phaseTimers = {};

  let turnEl = null;

  try {
    if (!isFollowup) {
      // ---- PHASE 1: Upload ----
      setPhase(phaseUpload, 'active');
      setSubText('upload', 'Preparing file…');
      phaseTimers.upload = Date.now();
      statusEl.classList.remove('hidden');
      statusText.textContent = 'Preparing upload…';

      await delay(180);

      setPhase(phaseUpload, 'done', Date.now() - phaseTimers.upload);
      setSubText('upload', 'File ready');
      fillConnector(conn12);
      statusEl.classList.add('hidden');

      // ---- PHASE 2: Preprocess ----
      setPhase(phasePreprocess, 'active');
      phaseTimers.preprocess = Date.now();
      startSubMessages('preprocess', SUB_MESSAGES.preprocess);
      statusEl.classList.remove('hidden');
      statusText.textContent = 'Running OCR + CV pipeline…';

      if (!currentDiagramId) {
        currentDiagramId = await ingestDiagram(selectedFile);
      }

      stopSubMessages('preprocess');
      setPhase(phasePreprocess, 'done', Date.now() - phaseTimers.preprocess);
      setSubText('preprocess', 'Complete');
      fillConnector(conn23);
      statusEl.classList.add('hidden');

    } else {
      // Follow-up: diagram already ingested — mark phases 1+2 as skipped
      setPhase(phaseUpload, 'skipped');
      setSubText('upload', 'Cached');
      fillConnector(conn12);
      setPhase(phasePreprocess, 'skipped');
      setSubText('preprocess', 'Reusing data');
      fillConnector(conn23);

      // Append placeholder immediately
      turnEl = appendConversationTurnPlaceholder(queryText);
      followupQuery.value = '';
      followupQuery.style.height = '';
      scrollToBottom();
    }

    // ---- PHASE 3: AI Analysis ----
    setPhase(phaseAnalyze, 'active');
    phaseTimers.analyze = Date.now();
    startSubMessages('analyze', SUB_MESSAGES.analyze);

    const result = await analyzeQuery(currentDiagramId, queryText);

    stopSubMessages('analyze');
    setPhase(phaseAnalyze, 'done', Date.now() - phaseTimers.analyze);
    setSubText('analyze', 'Complete');
    fillConnector(conn34);

    // ---- PHASE 4: Results ----
    setPhase(phaseResults, 'active');
    setSubText('results', 'Rendering…');
    phaseTimers.results = Date.now();

    await delay(220);

    setPhase(phaseResults, 'done', Date.now() - phaseTimers.results);
    setSubText('results', 'Ready');

    pipelineLiveBadge.classList.add('hidden');
    pipelineCompleteBadge.classList.remove('hidden');

    if (isFollowup) {
      updateConversationTurn(turnEl, result.text, result.toolCalls, currentDiagramId);
    } else {
      // Append Q+A turn to conversation history
      appendConversationTurn(queryText, currentDiagramId, result.text, result.toolCalls);
      
      // Show follow-up input (if hidden)
      followupSection.classList.remove('hidden');
      followupQuery.value = '';
      followupQuery.style.height = '';
      
      // Scroll to latest turn
      setTimeout(() => {
        const lastTurn = chatHistory.lastElementChild;
        if (lastTurn) lastTurn.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 140);
    }

  } catch (err) {
    console.error('Analysis pipeline failed:', err);
    stopAllSubMessages();
    statusEl.classList.add('hidden');
    pipelineLiveBadge.classList.add('hidden');

    [phaseUpload, phasePreprocess, phaseAnalyze, phaseResults].forEach(el => {
      if (el.classList.contains('active')) {
        el.classList.remove('active');
        el.classList.add('error');
        const sub = el.querySelector('.phase-sub');
        if (sub) sub.textContent = 'Failed';
      }
    });

    if (isFollowup && turnEl) {
      updateConversationTurnError(turnEl, err.message || 'An unexpected error occurred.');
    } else {
      appendErrorTurn(queryText, err.message || 'An unexpected error occurred.');
      followupSection.classList.remove('hidden');
    }

  } finally {
    isRunning = false;
    analyzeBtn.disabled = false;
    analyzeBtn.querySelector('span').textContent = 'Analyze Diagram';
    followupQuery.disabled = false;
    followupBtn.disabled = !followupQuery.value.trim();
  }
}

// ==========================================================================
// Workspace Activation
// ==========================================================================

function activateWorkspace() {
  if (isWorkspaceActive) return;
  isWorkspaceActive = true;
  workspace.classList.add('workspace-active');
  document.querySelector('.container').classList.add('workspace-active');
  // Re-fit the image after layout shift
  requestAnimationFrame(() => requestAnimationFrame(fitImage));
}

// ==========================================================================
// Conversation Turn Rendering
// ==========================================================================

/**
 * Append a question + answer pair to the chat history.
 */
function appendConversationTurn(question, diagramId, text, toolCalls) {
  conversationHistory.push({ question, text, toolCalls });

  const turn = document.createElement('div');
  turn.className = 'conv-turn';

  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const questionHtml = `
    <div class="conv-question">
      <div class="conv-q-inner">
        <div class="conv-question-bubble">${escapeHtml(question)}</div>
        <div class="conv-question-meta">${timestamp}</div>
      </div>
    </div>`;

  const answerHtml = `
    <div class="conv-answer">
      ${buildAnswerInnerHtml(text, toolCalls, diagramId)}
    </div>`;

  turn.innerHTML = questionHtml + answerHtml;
  chatHistory.appendChild(turn);
}

function appendConversationTurnPlaceholder(question) {
  const turn = document.createElement('div');
  turn.className = 'conv-turn';

  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const questionHtml = `
    <div class="conv-question">
      <div class="conv-q-inner">
        <div class="conv-question-bubble">${escapeHtml(question)}</div>
        <div class="conv-question-meta">${timestamp}</div>
      </div>
    </div>`;

  const answerHtml = `
    <div class="conv-answer">
      <div class="result-content glass-panel-inner conv-answer-text">
        <div class="thinking-placeholder">
          <div class="thinking-spinner"></div>
          <span>Thinking...</span>
        </div>
      </div>
    </div>`;

  turn.innerHTML = questionHtml + answerHtml;
  chatHistory.appendChild(turn);
  
  // Add to history (incomplete)
  conversationHistory.push({ question, text: null, toolCalls: [] });

  return turn;
}

function updateConversationTurn(turnEl, text, toolCalls, diagramId) {
  // Update state
  const lastTurn = conversationHistory[conversationHistory.length - 1];
  if (lastTurn) { // Assuming it's the right one
    lastTurn.text = text;
    lastTurn.toolCalls = toolCalls;
  }

  const answerEl = turnEl.querySelector('.conv-answer');
  if (!answerEl) return;

  answerEl.innerHTML = buildAnswerInnerHtml(text, toolCalls, diagramId);
  scrollToBottom();
}

function updateConversationTurnError(turnEl, detail) {
  // Update state
  const lastTurn = conversationHistory[conversationHistory.length - 1];
  if (lastTurn) {
    lastTurn.error = detail;
  }

  const answerEl = turnEl.querySelector('.conv-answer');
  if (!answerEl) return;

  answerEl.innerHTML = `
    <div class="result-meta">
      <span class="badge error">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        Analysis Failed
      </span>
    </div>
    <div class="result-content glass-panel-inner" style="color:var(--error); font-size:0.9rem;">
      ${escapeHtml(detail)}
    </div>`;
  
  scrollToBottom();
}

function buildAnswerInnerHtml(text, toolCalls, diagramId) {
  const metaHtml = buildResultMetaHtml(diagramId);
  const toolHtml = toolCalls && toolCalls.length > 0
    ? `<div class="tool-timeline conv-tool-timeline">${buildToolCallsHtml(toolCalls)}</div>`
    : '';
  return `
    <div class="result-meta">${metaHtml}</div>
    ${toolHtml}
    <div class="result-content markdown-body glass-panel-inner conv-answer-text">
      ${formatMarkdown(text)}
    </div>`;
}

/**
 * Append a failed-turn placeholder to the chat history.
 */
function appendErrorTurn(question, detail) {
  conversationHistory.push({ question, text: null, error: detail });

  const turn = document.createElement('div');
  turn.className = 'conv-turn';
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  turn.innerHTML = `
    <div class="conv-question">
      <div class="conv-q-inner">
        <div class="conv-question-bubble">${escapeHtml(question)}</div>
        <div class="conv-question-meta">${timestamp}</div>
      </div>
    </div>
    <div class="conv-answer">
      <div class="result-meta">
        <span class="badge error">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          Analysis Failed
        </span>
      </div>
      <div class="result-content glass-panel-inner" style="color:var(--error); font-size:0.9rem;">
        ${escapeHtml(detail)}
      </div>
    </div>`;

  chatHistory.appendChild(turn);
}

function scrollToBottom() {
  setTimeout(() => {
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }, 50); // Small timeout to allow DOM updates
}

/**
 * Build the result-meta HTML string (badges + visualization link).
 */
function buildResultMetaHtml(diagramId) {
  return `
    <span class="badge success">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
        <polyline points="22 4 12 14.01 9 11.01"/>
      </svg>
      Analysis Complete
    </span>
    <span class="badge id-badge" title="Diagram ID: ${diagramId}">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="9" y1="3" x2="9" y2="21"/>
      </svg>
      ${diagramId.substring(0, 8)}…
    </span>
    <a href="${API}/visualization/${diagramId}" target="_blank" class="view-link"
       title="Open interactive SVG visualization">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
      <span>Interactive Visualization</span>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
           stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
        <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
      </svg>
    </a>`;
}

// ==========================================================================
// Pipeline Helper Functions
// ==========================================================================

function setPhase(phaseEl, state, durationMs = null) {
  phaseEl.className = `pipeline-phase ${state}`;
  if (state === 'done' && durationMs !== null) {
    const timingEl = phaseEl.querySelector('.phase-timing');
    if (timingEl) {
      timingEl.innerHTML =
        `<span class="phase-time-badge">${(durationMs / 1000).toFixed(1)}s</span>`;
    }
  }
}

function fillConnector(connEl) {
  requestAnimationFrame(() => connEl.classList.add('filled'));
}

function setSubText(phase, text) {
  const el = document.getElementById(`sub-${phase}`);
  if (el) el.textContent = text;
}

function startSubMessages(phase, messages) {
  let i = 0;
  setSubText(phase, messages[0]);
  _subMsgTimers[phase] = setInterval(() => {
    i = (i + 1) % messages.length;
    setSubText(phase, messages[i]);
  }, 1900);
}

function stopSubMessages(phase) {
  if (_subMsgTimers[phase]) {
    clearInterval(_subMsgTimers[phase]);
    delete _subMsgTimers[phase];
  }
}

function stopAllSubMessages() {
  Object.keys(_subMsgTimers).forEach(stopSubMessages);
}

/** Reset pipeline phases and connectors (does NOT clear chat history). */
function resetPipeline() {
  [phaseUpload, phasePreprocess, phaseAnalyze, phaseResults].forEach(el => {
    el.className = 'pipeline-phase pending';
    const timingEl = el.querySelector('.phase-timing');
    if (timingEl) timingEl.innerHTML = '';
  });

  setSubText('upload',     'File prepared');
  setSubText('preprocess', 'OCR · CV · Tiling');
  setSubText('analyze',    'ADK · Gemini · 5 Tools');
  setSubText('results',    'Ready to display');

  [conn12, conn23, conn34].forEach(c => c.classList.remove('filled'));
  stopAllSubMessages();

  pipelineCompleteBadge.classList.add('hidden');
  pipelineLiveBadge.classList.add('hidden');
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ==========================================================================
// Tool Call Timeline
// ==========================================================================

const TOOL_COLORS = {
  get_overview:       { bg: '#1e3a5f', border: '#457b9d', text: '#a8dadc' },
  inspect_zone:       { bg: '#2d1b4e', border: '#6c5ce7', text: '#a29bfe' },
  inspect_component:  { bg: '#4a2c17', border: '#e17055', text: '#fab1a0' },
  search_text:        { bg: '#0d3b3b', border: '#00cec9', text: '#81ecec' },
  trace_net:          { bg: '#3b1d3b', border: '#e84393', text: '#fd79a8' },
};

const TOOL_ICONS = {
  get_overview:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  inspect_zone:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
  inspect_component:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  search_text:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  trace_net:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
};

function toolActionLabel(toolName, args) {
  switch (toolName) {
    case 'get_overview':
      return 'Fetched diagram dimensions, component inventory & title block';
    case 'inspect_zone': {
      const x1 = args.x1 ?? 0, y1 = args.y1 ?? 0;
      const x2 = args.x2 ?? 100, y2 = args.y2 ?? 100;
      return `Zoomed into ${getRegionLabel(x1, y1, x2, y2)} region — retrieved SOM-annotated tiles`;
    }
    case 'inspect_component': {
      const cid = args.component_id ?? args.label ?? args.index ?? '?';
      return `Deep-dive crop on component [${cid}] with nearby context`;
    }
    case 'search_text': {
      const q = args.query ?? args.text ?? args.search_query ?? '?';
      return `Text search across all OCR labels: "${q}"`;
    }
    case 'trace_net': {
      const cid = args.component_id ?? args.from_id ?? args.start ?? '?';
      return `Traced electrical connections from component [${cid}]`;
    }
    default:
      return `Called ${toolName}`;
  }
}

function getRegionLabel(x1, y1, x2, y2) {
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
  const h = cx < 38 ? 'left' : cx > 62 ? 'right' : 'center';
  const v = cy < 38 ? 'top'  : cy > 62 ? 'bottom' : 'middle';
  if (v === 'middle' && h === 'center') return 'central';
  if (v === 'middle') return h;
  if (h === 'center') return v;
  return `${v}-${h}`;
}

function toolArgsInline(toolName, args) {
  if (!args) return '';
  const filtered = Object.entries(args).filter(([k]) => k !== 'diagram_id');
  if (!filtered.length) return '';
  if (toolName === 'inspect_zone') {
    const { x1 = 0, y1 = 0, x2 = 100, y2 = 100 } = args;
    return `<span class="tool-arg-key">zone:</span> <span class="tool-arg-val">(${x1}%, ${y1}%) → (${x2}%, ${y2}%)</span>`;
  }
  return filtered
    .map(([k, v]) =>
      `<span class="tool-arg-key">${escapeHtml(k)}:</span> ` +
      `<span class="tool-arg-val">${escapeHtml(String(v).substring(0, 80))}</span>`
    )
    .join(' <span class="tool-arg-sep">·</span> ');
}

/**
 * Build tool-call timeline HTML (returns string, does not set DOM).
 * The toggle handler uses event delegation via toggleToolTimeline(btn).
 */
function buildToolCallsHtml(toolCalls) {
  const totalMs  = toolCalls.reduce((s, tc) => s + (tc.duration_ms || 0), 0);
  const totalSec = (totalMs / 1000).toFixed(1);
  const maxMs    = Math.max(...toolCalls.map(tc => tc.duration_ms || 0), 1);

  let html = `
    <div class="tool-timeline-header" onclick="toggleToolTimeline(this)">
      <div class="tool-timeline-title">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
        </svg>
        <span>Agent Activity</span>
        <span class="tool-count-badge">${toolCalls.length} tool call${toolCalls.length !== 1 ? 's' : ''}</span>
        <span class="tool-total-time">${totalSec}s total</span>
      </div>
      <svg class="tool-chevron" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </div>
    <div class="tool-timeline-body">`;

  toolCalls.forEach((tc, i) => {
    const colors    = TOOL_COLORS[tc.tool_name] || { bg: '#1c1e29', border: '#32364a', text: '#a4b0be' };
    const icon      = TOOL_ICONS[tc.tool_name] || '';
    const duration  = tc.duration_ms != null
      ? tc.duration_ms >= 1000 ? (tc.duration_ms / 1000).toFixed(1) + 's' : Math.round(tc.duration_ms) + 'ms'
      : '—';
    const barPct    = Math.round(((tc.duration_ms || 0) / maxMs) * 100);
    const successIco = tc.success
      ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00b894" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
      : '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d63031" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    const actionLabel = toolActionLabel(tc.tool_name, tc.args || {});
    const argsInline  = toolArgsInline(tc.tool_name, tc.args);
    const summaryChips = tc.result_summary
      ? tc.result_summary.split(/[,;]/).map(s => s.trim()).filter(Boolean)
          .map(s => `<span class="tool-result-chip">${escapeHtml(s)}</span>`).join('')
      : '';

    html += `
      <div class="tool-call-card" style="border-left-color:${colors.border}; --tool-bg:${colors.bg}; --tool-border:${colors.border};">
        <div class="tool-call-main">
          <span class="tool-step-badge" style="background:${colors.border}20; color:${colors.text}; border-color:${colors.border}40;">${i + 1}</span>
          <div class="tool-call-icon" style="color:${colors.text}">${icon}</div>
          <div class="tool-call-info">
            <span class="tool-call-name" style="color:${colors.text}">${escapeHtml(tc.tool_name)}</span>
          </div>
          <div class="tool-call-badges">
            <span class="tool-duration-badge">${duration}</span>
            <span class="tool-status-icon">${successIco}</span>
          </div>
        </div>
        <div class="tool-action-label">${escapeHtml(actionLabel)}</div>
        <div class="tool-timing-bar-wrap">
          <div class="tool-timing-bar-fill" style="width:${barPct}%; background:${colors.border};"></div>
        </div>
        <div class="tool-details-row">
          ${argsInline  ? `<div class="tool-call-args">${argsInline}</div>` : ''}
          ${summaryChips ? `<div class="tool-result-chips">${summaryChips}</div>` : ''}
          ${tc.error    ? `<div class="tool-call-error">${escapeHtml(tc.error)}</div>` : ''}
        </div>
      </div>`;
  });

  html += '</div>';
  return html;
}

/**
 * Toggle the tool-call timeline body open/closed.
 * Called with the header button element; finds parent .tool-timeline.
 */
function toggleToolTimeline(btn) {
  const timeline = btn.closest('.tool-timeline');
  if (!timeline) return;
  const body    = timeline.querySelector('.tool-timeline-body');
  const chevron = timeline.querySelector('.tool-chevron');
  if (body)    body.classList.toggle('collapsed');
  if (chevron) chevron.classList.toggle('rotated');
}

// ==========================================================================
// Markdown Formatter (lightweight, no external library)
// ==========================================================================

function formatMarkdown(text) {
  if (!text) return '';

  let out = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  out = out.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  out = out.replace(/^### (.+)$/gim, '<h3>$1</h3>');
  out = out.replace(/^## (.+)$/gim,  '<h2>$1</h2>');
  out = out.replace(/^# (.+)$/gim,   '<h1>$1</h1>');
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g,     '<em>$1</em>');
  out = out.replace(/^(?:-|\*)\s+(.+)$/gim, '<li>$1</li>');
  out = out.replace(/(<li>[\s\S]*?<\/li>(?:\n<li>[\s\S]*?<\/li>)*)/gim, '<ul>$1</ul>');
  out = out.replace(/^\d+\.\s+(.+)$/gim, '<li class="ol-item">$1</li>');
  out = out.replace(/(<li class="ol-item">[\s\S]*?<\/li>(?:\n<li class="ol-item">[\s\S]*?<\/li>)*)/gim,
    '<ol>$1</ol>');

  const blocks = out.split(/\n\n+/);
  out = blocks.map(b => {
    if (/^<\/?(h[1-6]|ul|ol|li|pre|blockquote)/.test(b.trim())) return b;
    return '<p>' + b.replace(/\n/g, '<br>') + '</p>';
  }).join('');

  return out;
}

// ==========================================================================
// Utilities
// ==========================================================================

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function showToast(msg, type = 'info') {
  if (!toastContainer) { alert(msg); return; }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = {
    info:    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error:   '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  };

  toast.innerHTML = `
    <div class="toast-icon">${icons[type] || icons.info}</div>
    <div class="toast-content">${escapeHtml(msg)}</div>
    <button class="toast-close" aria-label="Close">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>`;

  toastContainer.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));

  let hideTimeout = setTimeout(dismiss, 4500);
  toast.querySelector('.toast-close').addEventListener('click', () => {
    clearTimeout(hideTimeout);
    dismiss();
  });

  function dismiss() {
    toast.classList.remove('show');
    toast.addEventListener('transitionend', () => toast.remove());
  }
}

// ==========================================================================
// Boot
// ==========================================================================

document.addEventListener('DOMContentLoaded', init);
