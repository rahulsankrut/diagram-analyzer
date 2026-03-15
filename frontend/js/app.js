// ==========================================================================
// App Logic and State Management
// ==========================================================================

const API = ''; // change to e.g. "http://localhost:8080" if opening as file://

// DOM Elements
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

const resultsCard = document.getElementById('results-card');
const resultMeta = document.getElementById('result-meta');
const toolCallsEl = document.getElementById('tool-calls');
const resultText = document.getElementById('result-text');

const stepIngest = document.getElementById('step-ingest');
const stepAnalyze = document.getElementById('step-analyze');

// State
let selectedFile = null;
let currentDiagramId = null;

// ==========================================================================
// Initialization & Event Listeners
// ==========================================================================

function init() {
  setupDragAndDrop();
  setupFileInput();
  setupActions();
}

function setupDragAndDrop() {
  // Prevent default drag behaviors
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
  });

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  // Highlight drop zone
  ['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.add('drag-over');
    }, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, () => {
      dropZone.classList.remove('drag-over');
    }, false);
  });

  // Handle dropped files
  dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
      handleFile(files[0]);
    }
  }, false);
}

function setupFileInput() {
  fileInput.addEventListener('change', function () {
    if (this.files && this.files.length > 0) {
      handleFile(this.files[0]);
    }
  });
}

function setupActions() {
  clearBtn.addEventListener('click', clearFile);
  analyzeBtn.addEventListener('click', runAnalysis);

  // Auto-resize textarea
  queryTA.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
  });
}

// ==========================================================================
// File Handling
// ==========================================================================

function handleFile(file) {
  // Check file type
  const validTypes = ['image/jpeg', 'image/png', 'image/tiff', 'image/tif'];

  // Tiff files sometimes don't have perfect mime types based on OS, check extension too
  const extension = file.name.split('.').pop().toLowerCase();
  const validExtensions = ['jpg', 'jpeg', 'png', 'tif', 'tiff'];

  if (!validTypes.includes(file.type) && !validExtensions.includes(extension)) {
    showToast('Please upload a valid image file (PNG, JPEG, TIFF).', 'error');
    return;
  }

  selectedFile = file;

  // Generate preview
  const reader = new FileReader();
  reader.readAsDataURL(file);
  reader.onloadend = function () {
    previewImg.src = reader.result;

    // Format file size
    const fileSizeStr = (file.size / (1024 * 1024)).toFixed(2) + ' MB';
    previewName.textContent = `${file.name} (${fileSizeStr})`;

    // Switch to preview mode
    dropZone.classList.add('hidden');
    previewWrap.classList.remove('hidden');
    analyzeBtn.disabled = false;

    // Reset previous results
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
}

// ==========================================================================
// API Interaction
// ==========================================================================

async function runAnalysis() {
  if (!selectedFile) return;

  const query = queryTA.value.trim();
  if (!query) {
    queryTA.focus();
    // Add brief validation animation
    queryTA.style.border = '1px solid var(--error)';
    setTimeout(() => queryTA.style.border = '', 1000);
    return;
  }

  // Update UI for loading state
  setLoading(true, 'Uploading and ingesting diagram...');
  resetResults();

  try {
    // Phase 1: Ingestion (if we don't already have an ID for this file)
    if (!currentDiagramId) {
      currentDiagramId = await ingestDiagram(selectedFile);
    }

    // Update Progress
    markStep(stepIngest, 'done');
    markStep(stepAnalyze, 'active');
    setLoading(true, 'Analyzing diagram with AI agent...');

    // Phase 2: Analysis
    const result = await analyzeQuery(currentDiagramId, query);

    // Success
    setLoading(false);
    displayResult(currentDiagramId, result.text, result.toolCalls);

  } catch (error) {
    // Error Handling
    console.error('Analysis flow failed:', error);
    setLoading(false);
    displayError('Analysis Failed', error.message || 'An unexpected error occurred.');
  }
}

async function ingestDiagram(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API}/ingest`, {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Server Error (${response.status}): ${errorText}`);
  }

  const data = await response.json();
  if (!data.success) {
    throw new Error(data.error_message || 'Diagram ingestion failed on the server.');
  }

  return data.diagram_id;
}

async function analyzeQuery(diagramId, query) {
  const response = await fetch(`${API}/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      diagram_id: diagramId,
      query: query,
      user_id: 'web-ui-user'
    })
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Analysis Error (${response.status}): ${errorText}`);
  }

  const data = await response.json();
  return { text: data.response, toolCalls: data.tool_calls || [] };
}

// ==========================================================================
// UI Updates & Utilities
// ==========================================================================

function setLoading(isLoading, text = '') {
  analyzeBtn.disabled = isLoading;

  // Show/hide spinner
  if (isLoading) {
    analyzeBtn.querySelector('span').textContent = 'Processing...';
    statusEl.classList.remove('hidden');
    statusText.textContent = text;
    resultsCard.classList.remove('hidden'); // Show card structure early during loading
  } else {
    analyzeBtn.querySelector('span').textContent = 'Analyze Diagram';
    statusEl.classList.add('hidden');
  }
}

function resetResults() {
  resultMeta.innerHTML = '';
  resultText.innerHTML = '';
  toolCallsEl.innerHTML = '';
  toolCallsEl.classList.add('hidden');
  markStep(stepIngest, '');
  markStep(stepAnalyze, '');
}

function markStep(element, state) {
  element.classList.remove('active', 'done');
  if (state) {
    element.classList.add(state);
  }
}

function displayResult(diagramId, text, toolCalls) {
  markStep(stepAnalyze, 'done');
  resultsCard.classList.remove('hidden');

  // Scroll to results smoothly
  setTimeout(() => {
    resultsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 100);

  // Set Metadata
  resultMeta.innerHTML = `
    <span class="badge success">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
      Analysis Complete
    </span>
    <span class="badge id-badge" title="Diagram ID">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
      ${diagramId.substring(0, 8)}...
    </span>
    <a href="${API}/visualization/${diagramId}" target="_blank" class="view-link" title="Open precise interactive view">
      <span>Interactive Visualization</span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
    </a>
  `;

  // Render tool call activity timeline
  if (toolCalls && toolCalls.length > 0) {
    renderToolCalls(toolCalls);
  }

  // Render markdown text (very basic parser since we don't have a library)
  resultText.innerHTML = formatMarkdown(text);
}

// ==========================================================================
// Tool Call Activity Timeline
// ==========================================================================

const TOOL_COLORS = {
  get_overview:       { bg: '#1e3a5f', border: '#457b9d', text: '#a8dadc' },
  inspect_zone:       { bg: '#2d1b4e', border: '#6c5ce7', text: '#a29bfe' },
  inspect_component:  { bg: '#4a2c17', border: '#e17055', text: '#fab1a0' },
  search_text:        { bg: '#0d3b3b', border: '#00cec9', text: '#81ecec' },
  trace_net:          { bg: '#3b1d3b', border: '#e84393', text: '#fd79a8' },
};

const TOOL_ICONS = {
  get_overview:       '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
  inspect_zone:       '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
  inspect_component:  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>',
  search_text:        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  trace_net:          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
};

function renderToolCalls(toolCalls) {
  const totalMs = toolCalls.reduce((sum, tc) => sum + (tc.duration_ms || 0), 0);
  const totalSec = (totalMs / 1000).toFixed(1);

  let html = `
    <div class="tool-timeline-header" onclick="toggleToolTimeline()">
      <div class="tool-timeline-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        <span>Agent Activity</span>
        <span class="tool-count-badge">${toolCalls.length} tool call${toolCalls.length !== 1 ? 's' : ''}</span>
        <span class="tool-total-time">${totalSec}s</span>
      </div>
      <svg class="tool-chevron" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
    </div>
    <div class="tool-timeline-body">
  `;

  toolCalls.forEach((tc, i) => {
    const colors = TOOL_COLORS[tc.tool_name] || { bg: '#1c1e29', border: '#32364a', text: '#a4b0be' };
    const icon = TOOL_ICONS[tc.tool_name] || '';
    const duration = tc.duration_ms ? (tc.duration_ms / 1000).toFixed(2) + 's' : '—';
    const statusIcon = tc.success
      ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00b894" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>'
      : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d63031" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    const argsStr = tc.args ? Object.entries(tc.args)
      .filter(([k]) => k !== 'diagram_id')
      .map(([k, v]) => `<span class="tool-arg-key">${escapeHtml(k)}:</span> <span class="tool-arg-val">${escapeHtml(String(v).substring(0, 80))}</span>`)
      .join(', ') : '';

    html += `
      <div class="tool-call-card" style="border-left-color: ${colors.border}; --tool-bg: ${colors.bg};">
        <div class="tool-call-main" onclick="toggleToolDetail(${i})">
          <div class="tool-call-icon" style="color: ${colors.text}">${icon}</div>
          <div class="tool-call-info">
            <span class="tool-call-name" style="color: ${colors.text}">${escapeHtml(tc.tool_name)}</span>
            ${tc.result_summary ? `<span class="tool-call-summary">${escapeHtml(tc.result_summary)}</span>` : ''}
          </div>
          <div class="tool-call-badges">
            <span class="tool-duration-badge">${duration}</span>
            <span class="tool-status-icon">${statusIcon}</span>
          </div>
        </div>
        <div class="tool-call-detail hidden" id="tool-detail-${i}">
          ${argsStr ? `<div class="tool-call-args">${argsStr}</div>` : ''}
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
  const detail = document.getElementById(`tool-detail-${index}`);
  if (detail) {
    detail.classList.toggle('hidden');
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function displayError(title, detail) {
  resultsCard.classList.remove('hidden');
  resetResults(); // Clear steps

  resultMeta.innerHTML = `
    <span class="badge error">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
      ${title}
    </span>
  `;

  resultText.textContent = detail;
  resultText.style.color = 'var(--error)';
}

function formatMarkdown(text) {
  if (!text) return '';

  // 1. Sanitize HTML
  let formatted = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 2. Code blocks (do this early to avoid messing up internals)
  formatted = formatted.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

  // 3. Inline code
  formatted = formatted.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // 4. Headers
  formatted = formatted.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  formatted = formatted.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  formatted = formatted.replace(/^# (.*$)/gim, '<h1>$1</h1>');

  // 5. Bold & Italic
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 6. Unordered Lists
  // Match lines starting with a dash or asterisk, wrap in <li>, then wrap the group in <ul>
  formatted = formatted.replace(/^(?:-|\*)\s+(.*)$/gim, '<li>$1</li>');
  // Hacky but works for basic cases without a full parser: wrap contiguous <li>s
  formatted = formatted.replace(/(<li>.*<\/li>(?:\n<li>.*<\/li>)*)/gim, '<ul>$1</ul>');

  // 7. Numbered Lists
  formatted = formatted.replace(/^\d+\.\s+(.*)$/gim, '<li class="ol-item">$1</li>');
  formatted = formatted.replace(/(<li class="ol-item">.*<\/li>(?:\n<li class="ol-item">.*<\/li>)*)/gim, '<ol>$1</ol>');

  // 8. Paragraphs
  // Split on double newlines to separate paragraphs
  const blocks = formatted.split(/\n\n+/);
  formatted = blocks.map(block => {
    // If it's already an HTML block element, leave it alone
    if (/^<\/?(h[1-6]|ul|ol|li|pre|blockquote)/.test(block.trim())) {
      return block;
    }
    // Otherwise wrap it in a <p>, replacing single newlines with <br>
    return '<p>' + block.replace(/\n/g, '<br>') + '</p>';
  }).join('');

  return formatted;
}

// Simple toast notification fallback
function showToast(message, type = 'info') {
  alert(message); // Since this is a simple UI, fallback to alert if no toast container
}

// Initialize the app
document.addEventListener('DOMContentLoaded', init);
