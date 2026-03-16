// ==========================================================================
// CAD Diagram Analyzer — Frontend App Logic
// ==========================================================================

const API = ''; // change to e.g. "http://localhost:8080" if opening as file://

// ==========================================================================
// DOM References
// ==========================================================================

// Input card
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const previewWrap = document.getElementById('preview-wrap');
const previewImg = document.getElementById('preview-img');
const previewName = document.getElementById('preview-name');
const clearBtn = document.getElementById('clear-btn');
const queryTA = document.getElementById('query');
const analyzeBtn = document.getElementById('analyze-btn');
const statusEl = document.getElementById('status');
const statusText = document.getElementById('status-text');

// Results card
const resultsCard = document.getElementById('results-card');
const resultMeta = document.getElementById('result-meta');
const toolCallsEl = document.getElementById('tool-calls');
const resultText = document.getElementById('result-text');

// Toast container
const toastContainer = document.getElementById('toast-container');

// Pipeline badges
const pipelineLiveBadge = document.getElementById('pipeline-live-badge');
const pipelineCompleteBadge = document.getElementById('pipeline-complete-badge');
const resultsDivider = document.getElementById('results-divider');

// Pipeline phase elements
const phaseUpload = document.getElementById('phase-upload');
const phasePreprocess = document.getElementById('phase-preprocess');
const phaseAnalyze = document.getElementById('phase-analyze');
const phaseResults = document.getElementById('phase-results');

// Connector elements
const conn12 = document.getElementById('conn-12');
const conn23 = document.getElementById('conn-23');
const conn34 = document.getElementById('conn-34');

// ==========================================================================
// State
// ==========================================================================

let selectedFile = null;
let currentDiagramId = null;
let _subMsgTimers = {};

// ==========================================================================
// Initialization
// ==========================================================================

function init() {
  setupDragAndDrop();
  setupFileInput();
  setupActions();
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
  clearBtn.addEventListener('click', clearFile);
  analyzeBtn.addEventListener('click', runAnalysis);

  queryTA.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = this.scrollHeight + 'px';
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
    showToast('Please upload a valid image file (PNG, JPEG, TIFF).');
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

    // Reset previous results when a new file is chosen
    resultsCard.classList.add('hidden');
    currentDiagramId = null;
  };
}

function clearFile() {
  selectedFile = null;
  fileInput.value = '';
  currentDiagramId = null;

  previewWrap.classList.add('hidden');
  dropZone.classList.remove('hidden');
  analyzeBtn.disabled = true;
  resultsCard.classList.add('hidden');

  // reset zoom logic
  scale = 1;
  panX = 0;
  panY = 0;
  updateTransform();
}

// ==========================================================================
// Image Pan & Zoom
// ==========================================================================

let scale = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let startX = 0;
let startY = 0;
const previewViewport = document.getElementById('preview-viewport');

function setupImagePanZoom() {
  if (!previewViewport) return;

  // Zoom via scroll wheel
  previewViewport.addEventListener('wheel', (e) => {
    e.preventDefault();
    const zoomFactor = -0.002;
    const scrollDelta = e.deltaY;

    // Get cursor position relative to viewport
    const rect = previewViewport.getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;

    const newScale = Math.max(0.2, Math.min(scale + (scrollDelta * zoomFactor), 15));

    if (newScale !== scale) {
      // Adjust pan to zoom into cursor
      panX = cursorX - (cursorX - panX) * (newScale / scale);
      panY = cursorY - (cursorY - panY) * (newScale / scale);
      scale = newScale;
      updateTransform();
    }
  });

  // Pan via click and drag
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
    updateTransform();
  });

  document.addEventListener('mouseup', () => {
    if (isPanning) {
      isPanning = false;
      previewViewport.style.cursor = 'grab';
    }
  });

  // Double click to reset
  previewViewport.addEventListener('dblclick', () => {
    // fit-to-width strategy fallback 
    scale = 1;
    panX = 0;
    panY = 0;

    const imgRatio = previewImg.naturalWidth / previewImg.naturalHeight;
    const viewRatio = previewViewport.clientWidth / previewViewport.clientHeight;
    if (imgRatio < viewRatio) {
      scale = previewViewport.clientHeight / previewImg.naturalHeight;
      panX = (previewViewport.clientWidth - (previewImg.naturalWidth * scale)) / 2;
    } else {
      scale = previewViewport.clientWidth / previewImg.naturalWidth;
      panY = (previewViewport.clientHeight - (previewImg.naturalHeight * scale)) / 2;
    }
    updateTransform();
  });
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
// Main Analysis Flow — 4-Phase Pipeline
// ==========================================================================

// Sub-messages that cycle during each active phase (simulated progress)
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

async function runAnalysis() {
  if (!selectedFile) return;

  const query = queryTA.value.trim();
  if (!query) {
    queryTA.style.boxShadow = '0 0 0 2px var(--error)';
    setTimeout(() => { queryTA.style.boxShadow = ''; }, 1200);
    queryTA.focus();
    return;
  }

  // ---- Reset + show pipeline skeleton ----
  resetResults();
  analyzeBtn.disabled = true;
  analyzeBtn.querySelector('span').textContent = 'Processing…';

  resultsCard.classList.remove('hidden');
  pipelineLiveBadge.classList.remove('hidden');
  pipelineCompleteBadge.classList.add('hidden');

  // Scroll to results card so the pipeline is visible
  setTimeout(() => resultsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 80);

  const phaseTimers = {};

  try {
    // ------------------------------------------------------------------
    // PHASE 1: Upload  (file is already in memory — near-instant)
    // ------------------------------------------------------------------
    setPhase(phaseUpload, 'active');
    setSubText('upload', 'Preparing file…');
    phaseTimers.upload = Date.now();

    await delay(180); // brief visual beat

    setPhase(phaseUpload, 'done', Date.now() - phaseTimers.upload);
    setSubText('upload', 'File ready');
    fillConnector(conn12);

    // ------------------------------------------------------------------
    // PHASE 2: Preprocess  (OCR + CV + Tiling  →  POST /ingest)
    // ------------------------------------------------------------------
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

    // ------------------------------------------------------------------
    // PHASE 3: AI Analysis  (ADK Agent + tools  →  POST /analyze)
    // ------------------------------------------------------------------
    setPhase(phaseAnalyze, 'active');
    phaseTimers.analyze = Date.now();
    startSubMessages('analyze', SUB_MESSAGES.analyze);
    statusEl.classList.remove('hidden');
    statusText.textContent = 'Analyzing with Gemini agent…';

    const result = await analyzeQuery(currentDiagramId, query);

    stopSubMessages('analyze');
    setPhase(phaseAnalyze, 'done', Date.now() - phaseTimers.analyze);
    setSubText('analyze', 'Complete');
    fillConnector(conn34);
    statusEl.classList.add('hidden');

    // ------------------------------------------------------------------
    // PHASE 4: Results  (render the response)
    // ------------------------------------------------------------------
    setPhase(phaseResults, 'active');
    setSubText('results', 'Rendering insights…');
    phaseTimers.results = Date.now();

    await delay(280); // brief moment before content appears

    setPhase(phaseResults, 'done', Date.now() - phaseTimers.results);
    setSubText('results', 'Ready');

    // Show "all phases complete" badge, hide "live" badge
    pipelineLiveBadge.classList.add('hidden');
    pipelineCompleteBadge.classList.remove('hidden');

    // Reveal result content
    resultsDivider.classList.remove('hidden');
    displayResult(currentDiagramId, result.text, result.toolCalls);

  } catch (err) {
    console.error('Analysis pipeline failed:', err);

    // Mark the currently active phase as error
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

    resultsDivider.classList.remove('hidden');
    displayError('Analysis Failed', err.message || 'An unexpected error occurred.');
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.querySelector('span').textContent = 'Analyze Diagram';
  }
}

// ==========================================================================
// Pipeline Helper Functions
// ==========================================================================

/**
 * Set the visual state of a pipeline phase node.
 * @param {HTMLElement} phaseEl - The .pipeline-phase element
 * @param {'pending'|'active'|'done'|'error'|'skipped'} state
 * @param {number|null} durationMs - If done, show a timing badge
 */
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

/**
 * Animate the connector line between two phases as "filled".
 * @param {HTMLElement} connEl - The .pipeline-conn element
 */
function fillConnector(connEl) {
  // requestAnimationFrame ensures the CSS transition fires properly
  requestAnimationFrame(() => connEl.classList.add('filled'));
}

/**
 * Update the sub-description text of a phase.
 * @param {'upload'|'preprocess'|'analyze'|'results'} phase
 * @param {string} text
 */
function setSubText(phase, text) {
  const el = document.getElementById(`sub-${phase}`);
  if (el) el.textContent = text;
}

/**
 * Cycle through sub-messages while a phase is active.
 * @param {string} phase
 * @param {string[]} messages
 */
function startSubMessages(phase, messages) {
  let i = 0;
  setSubText(phase, messages[0]);
  _subMsgTimers[phase] = setInterval(() => {
    i = (i + 1) % messages.length;
    setSubText(phase, messages[i]);
  }, 1900);
}

/** Stop cycling sub-messages for a specific phase. */
function stopSubMessages(phase) {
  if (_subMsgTimers[phase]) {
    clearInterval(_subMsgTimers[phase]);
    delete _subMsgTimers[phase];
  }
}

/** Stop all active sub-message timers (used on error). */
function stopAllSubMessages() {
  Object.keys(_subMsgTimers).forEach(stopSubMessages);
}

/** Promise-based delay. */
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ==========================================================================
// UI State Helpers
// ==========================================================================

/**
 * Reset all pipeline phases + result content for a fresh run.
 */
function resetResults() {
  // Reset all phase nodes to pending
  [phaseUpload, phasePreprocess, phaseAnalyze, phaseResults].forEach(el => {
    el.className = 'pipeline-phase pending';
    const timingEl = el.querySelector('.phase-timing');
    if (timingEl) timingEl.innerHTML = '';
  });

  // Reset sub-texts to defaults
  setSubText('upload', 'File prepared');
  setSubText('preprocess', 'OCR · CV · Tiling');
  setSubText('analyze', 'ADK · Gemini · 5 Tools');
  setSubText('results', 'Ready to display');

  // Reset connector fills
  [conn12, conn23, conn34].forEach(c => c.classList.remove('filled'));

  // Stop any running sub-message timers
  stopAllSubMessages();

  // Clear result content
  resultMeta.innerHTML = '';
  resultText.innerHTML = '';
  resultText.style.color = '';
  toolCallsEl.innerHTML = '';
  toolCallsEl.classList.add('hidden');

  // Hide divider + badges
  resultsDivider.classList.add('hidden');
  pipelineCompleteBadge.classList.add('hidden');
  pipelineLiveBadge.classList.add('hidden');
}

// ==========================================================================
// Display Functions
// ==========================================================================

/**
 * Populate the results section after a successful analysis.
 * @param {string} diagramId
 * @param {string} text - Agent response (markdown)
 * @param {Array}  toolCalls - Tool call metadata list
 */
function displayResult(diagramId, text, toolCalls) {
  // Meta row: badges + viz link
  resultMeta.innerHTML = `
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
    </a>
  `;

  // Tool call timeline
  if (toolCalls && toolCalls.length > 0) {
    renderToolCalls(toolCalls);
  }

  // Render markdown response
  resultText.innerHTML = formatMarkdown(text);

  // Smooth scroll to content
  setTimeout(() => {
    resultText.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 120);
}

/**
 * Show an error state in the results section.
 */
function displayError(title, detail) {
  resultMeta.innerHTML = `
    <span class="badge error">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>
      ${escapeHtml(title)}
    </span>
  `;
  resultText.textContent = detail;
  resultText.style.color = 'var(--error)';
}

// ==========================================================================
// Tool Call Activity Timeline
// ==========================================================================

const TOOL_COLORS = {
  get_overview: { bg: '#1e3a5f', border: '#457b9d', text: '#a8dadc' },
  inspect_zone: { bg: '#2d1b4e', border: '#6c5ce7', text: '#a29bfe' },
  inspect_component: { bg: '#4a2c17', border: '#e17055', text: '#fab1a0' },
  search_text: { bg: '#0d3b3b', border: '#00cec9', text: '#81ecec' },
  trace_net: { bg: '#3b1d3b', border: '#e84393', text: '#fd79a8' },
};

const TOOL_ICONS = {
  get_overview:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  inspect_zone:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
  inspect_component:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  search_text:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  trace_net:
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
};

/**
 * Render the collapsible agent activity timeline.
 * @param {Array} toolCalls - List of tool call records from the API
 */
function renderToolCalls(toolCalls) {
  const totalMs = toolCalls.reduce((s, tc) => s + (tc.duration_ms || 0), 0);
  const totalSec = (totalMs / 1000).toFixed(1);

  let html = `
    <div class="tool-timeline-header" onclick="toggleToolTimeline()">
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
    <div class="tool-timeline-body">
  `;

  toolCalls.forEach((tc, i) => {
    const colors = TOOL_COLORS[tc.tool_name] || { bg: '#1c1e29', border: '#32364a', text: '#a4b0be' };
    const icon = TOOL_ICONS[tc.tool_name] || '';
    const duration = tc.duration_ms ? (tc.duration_ms / 1000).toFixed(2) + 's' : '—';
    const successIco = tc.success
      ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00b894" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>'
      : '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d63031" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    const argsHtml = tc.args
      ? Object.entries(tc.args)
        .filter(([k]) => k !== 'diagram_id')
        .map(([k, v]) =>
          `<span class="tool-arg-key">${escapeHtml(k)}:</span> ` +
          `<span class="tool-arg-val">${escapeHtml(String(v).substring(0, 100))}</span>`
        )
        .join(' &nbsp;·&nbsp; ')
      : '';

    html += `
      <div class="tool-call-card" style="border-left-color:${colors.border}; --tool-bg:${colors.bg};">
        <div class="tool-call-main" onclick="toggleToolDetail(${i})">
          <div class="tool-call-icon" style="color:${colors.text}">${icon}</div>
          <div class="tool-call-info">
            <span class="tool-call-name" style="color:${colors.text}">${escapeHtml(tc.tool_name)}</span>
            ${tc.result_summary
        ? `<span class="tool-call-summary">${escapeHtml(tc.result_summary)}</span>`
        : ''}
          </div>
          <div class="tool-call-badges">
            <span class="tool-duration-badge">${duration}</span>
            <span class="tool-status-icon">${successIco}</span>
          </div>
        </div>
        <div class="tool-call-detail hidden" id="tool-detail-${i}">
          ${argsHtml ? `<div class="tool-call-args">${argsHtml}</div>` : ''}
          ${tc.error ? `<div class="tool-call-error">${escapeHtml(tc.error)}</div>` : ''}
        </div>
      </div>
    `;
  });

  html += '</div>';
  toolCallsEl.innerHTML = html;
  toolCallsEl.classList.remove('hidden');
}

function toggleToolTimeline() {
  const body = toolCallsEl.querySelector('.tool-timeline-body');
  const chevron = toolCallsEl.querySelector('.tool-chevron');
  if (body) {
    body.classList.toggle('collapsed');
    chevron.classList.toggle('rotated');
  }
}

function toggleToolDetail(index) {
  const el = document.getElementById(`tool-detail-${index}`);
  if (el) el.classList.toggle('hidden');
}

// ==========================================================================
// Markdown Formatter (lightweight, no external library)
// ==========================================================================

function formatMarkdown(text) {
  if (!text) return '';

  // 1. Sanitize HTML entities
  let out = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 2. Code blocks
  out = out.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

  // 3. Inline code
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // 4. Headers
  out = out.replace(/^### (.+)$/gim, '<h3>$1</h3>');
  out = out.replace(/^## (.+)$/gim, '<h2>$1</h2>');
  out = out.replace(/^# (.+)$/gim, '<h1>$1</h1>');

  // 5. Bold & italic
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // 6. Unordered lists
  out = out.replace(/^(?:-|\*)\s+(.+)$/gim, '<li>$1</li>');
  out = out.replace(/(<li>[\s\S]*?<\/li>(?:\n<li>[\s\S]*?<\/li>)*)/gim, '<ul>$1</ul>');

  // 7. Ordered lists
  out = out.replace(/^\d+\.\s+(.+)$/gim, '<li class="ol-item">$1</li>');
  out = out.replace(/(<li class="ol-item">[\s\S]*?<\/li>(?:\n<li class="ol-item">[\s\S]*?<\/li>)*)/gim,
    '<ol>$1</ol>');

  // 8. Paragraphs
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
  if (!toastContainer) {
    alert(msg);
    return;
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = {
    info: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    error: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
  };

  toast.innerHTML = `
    <div class="toast-icon">${icons[type] || icons.info}</div>
    <div class="toast-content">${escapeHtml(msg)}</div>
    <button class="toast-close" aria-label="Close">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  `;

  toastContainer.appendChild(toast);

  // Trigger animation
  requestAnimationFrame(() => toast.classList.add('show'));

  // Autohide
  let hideTimeout = setTimeout(dismiss, 4000);

  // Close button
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
