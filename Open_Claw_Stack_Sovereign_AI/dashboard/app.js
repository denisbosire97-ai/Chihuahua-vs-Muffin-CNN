/**
 * Open Claw Stack — Dashboard JavaScript
 * ========================================
 * Real-time WebSocket client that drives all UI updates.
 *
 * Features:
 *   - WebSocket connection with auto-reconnect
 *   - Version-based state diffing (no redundant renders)
 *   - PRA phase visualization updates
 *   - Live agent card status rendering
 *   - Activity feed with timestamp
 *   - Execwall audit log display
 *   - Incident log rendering
 *   - Final report rendering (Markdown-lite)
 *   - Task submission via REST POST /task
 */

// ── Connection ─────────────────────────────────────
const WS_URL   = `ws://${location.host}/ws`;
const API_BASE = `${location.protocol}//${location.host}`;

let ws            = null;
let lastVersion   = -1;
let reconnectTimer= null;
let feedItems     = [];
let taskRunning   = false;

const AGENT_COLORS = {
  supervisor:       '#8b5cf6',
  security_auditor: '#ef4444',
  network_engineer: '#06b6d4',
  sysadmin:         '#3b82f6',
  product_lead:     '#10b981',
};

// ── Init ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  connect();

  // Enter key to submit
  document.getElementById('task-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') submitTask();
  });
});

// ── WebSocket ──────────────────────────────────────
function connect() {
  setConnectionStatus('connecting');

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setConnectionStatus('connected');
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  };

  ws.onmessage = (event) => {
    try {
      const state = JSON.parse(event.data);
      if (state.version !== lastVersion) {
        lastVersion = state.version;
        render(state);
      }
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };

  ws.onclose = () => {
    setConnectionStatus('disconnected');
    reconnectTimer = setTimeout(connect, 2500);
  };

  ws.onerror = () => {
    ws.close();
  };
}

// ── Task Submission ────────────────────────────────
async function submitTask() {
  const input = document.getElementById('task-input');
  const task  = input.value.trim();

  if (!task || taskRunning) return;

  const btn = document.getElementById('btn-run');
  setTaskRunning(true);

  try {
    const resp = await fetch(`${API_BASE}/task`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ task }),
    });
    const data = await resp.json();

    if (!resp.ok) {
      alert(`Error: ${data.error || 'Unknown error'}`);
      setTaskRunning(false);
      return;
    }

    // Clear report
    document.getElementById('report-body').innerHTML =
      '<div class="report-placeholder">⚡ Task running — live update in progress...</div>';
    input.value = '';

  } catch (err) {
    alert(`Connection error: ${err.message}`);
    setTaskRunning(false);
  }
}

async function resetSystem() {
  if (!confirm('Reset system state?')) return;
  await fetch(`${API_BASE}/reset`, { method: 'POST' });
  feedItems = [];
  document.getElementById('feed-list').innerHTML = '';
  document.getElementById('report-body').innerHTML =
    '<div class="report-placeholder">System reset. Enter a task to begin.</div>';
  lastVersion = -1;
}

function copyReport() {
  const text = document.getElementById('report-body').innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.btn-copy');
    btn.textContent = '✅ Copied!';
    setTimeout(() => btn.textContent = '📋 Copy', 1500);
  });
}

function clearReport() {
  document.getElementById('report-body').innerHTML =
    '<div class="report-placeholder">Report cleared.</div>';
}

// ── Master Render ──────────────────────────────────
function render(state) {
  renderPRAPhase(state.pra_phase);
  renderAgents(state.agents);
  renderMessages(state.messages);
  renderExecwall(state.execwall_audit);
  renderIncidents(state.incident_log);
  renderReport(state.final_report);
  renderChips(state);
  handleTaskState(state);
}

// ── PRA Phase ──────────────────────────────────────
function renderPRAPhase(phase) {
  const steps = ['perception', 'reasoning', 'action'];
  const phaseMap = {
    perception: 'perception',
    reasoning:  'reasoning',
    action:     'action',
    done:       null,
    idle:       null,
  };
  const active = phaseMap[phase] || null;

  steps.forEach(step => {
    const el = document.getElementById(`pra-${step}`);
    if (!el) return;
    el.classList.toggle('active', step === active);
  });
}

// ── Agent Cards ────────────────────────────────────
function renderAgents(agents) {
  Object.entries(agents).forEach(([name, data]) => {
    updateAgentCard(name, data);
  });
}

function updateAgentCard(name, data) {
  const card    = document.getElementById(`card-${name}`);
  const badge   = document.getElementById(`badge-${name}`);
  const output  = document.getElementById(`out-${name}`);
  const metrics = document.getElementById(`met-${name}`);
  const tools   = document.getElementById(`tools-${name}`);

  if (!card) return;

  const status = data.status || 'idle';
  const isActive = ['perceiving','reasoning','acting'].includes(status);
  const isDone   = status === 'done';
  const isError  = status === 'error';

  // Card border class
  card.className = `agent-card${name === 'product_lead' ? ' agent-card--wide' : ''} ${isActive ? 'active' : isDone ? 'done' : isError ? 'error' : 'idle'}`;

  // Badge
  if (badge) {
    badge.className  = `agent-status-badge ${status}`;
    badge.textContent = status.toUpperCase();
  }

  // Output
  if (output && data.last_output) {
    output.textContent = data.last_output;
  }

  // Metrics
  if (metrics) {
    const met = data.metrics || {};
    const tags = Object.entries(met)
      .filter(([k, v]) => typeof v !== 'object')
      .slice(0, 5)
      .map(([k, v]) => `<span class="metric-tag">${k}: ${v}</span>`)
      .join('');
    metrics.innerHTML = tags;
  }

  // Tool calls
  if (tools) {
    const calls = (data.tool_calls || []).slice(-4);
    tools.innerHTML = calls
      .map(t => `<span class="tool-tag">${escHtml(t.tool || '')}</span>`)
      .join('');
  }
}

// ── Activity Feed ──────────────────────────────────
let renderedMsgCount = 0;

function renderMessages(messages) {
  if (!messages || messages.length === renderedMsgCount) return;

  const feed  = document.getElementById('feed-list');
  const count = document.getElementById('feed-count');

  // Only append new messages
  const newMsgs = messages.slice(renderedMsgCount);
  renderedMsgCount = messages.length;

  newMsgs.forEach(msg => {
    const item = document.createElement('div');
    item.className = `feed-item feed-item--${msg.agent || 'system'}`;

    const ts = new Date(msg.timestamp * 1000);
    const time = ts.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const agentLabel = (msg.agent || 'system').replace('_', ' ').toUpperCase();

    item.innerHTML = `
      <span class="feed-time">${time}</span>
      <span class="feed-content">
        <strong style="color:${AGENT_COLORS[msg.agent] || '#a0a0c0'}">${agentLabel}</strong>
        &nbsp;${escHtml(msg.content).replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')}
      </span>
    `;
    feed.appendChild(item);
  });

  // Auto-scroll to bottom
  feed.scrollTop = feed.scrollHeight;
  if (count) count.textContent = `${messages.length} events`;
}

// ── Execwall ───────────────────────────────────────
let renderedEWCount = 0;

function renderExecwall(audit) {
  if (!audit || audit.length === renderedEWCount) return;

  const log = document.getElementById('execwall-log');
  const newEntries = audit.slice(renderedEWCount);
  renderedEWCount = audit.length;

  let allows = 0, denies = 0;
  audit.forEach(e => e.verdict === 'ALLOW' ? allows++ : denies++);

  document.getElementById('ew-allow').textContent = allows;
  document.getElementById('ew-deny').textContent  = denies;

  newEntries.forEach(entry => {
    const isAllow = entry.verdict === 'ALLOW';
    const div = document.createElement('div');
    div.className = `ew-entry ${isAllow ? 'ew-allow' : 'ew-deny'}`;
    div.innerHTML = `
      <span class="ew-verdict">${isAllow ? '✅' : '🚫'} ${entry.verdict}</span>
      <span class="ew-cmd">[${entry.agent}] ${escHtml((entry.command || '').slice(0, 60))}</span>
    `;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  });
}

// ── Incidents ──────────────────────────────────────
let renderedIncidentCount = 0;

function renderIncidents(incidents) {
  if (!incidents || incidents.length === renderedIncidentCount) return;

  const list     = document.getElementById('incidents-list');
  const newItems = incidents.slice(renderedIncidentCount);
  renderedIncidentCount = incidents.length;

  if (incidents.length > 0) {
    const empty = list.querySelector('.no-incidents');
    if (empty) empty.remove();
  }

  newItems.forEach(inc => {
    const div = document.createElement('div');
    div.className = 'incident-item';
    const ts  = inc.timestamp ? new Date(inc.timestamp * 1000).toLocaleTimeString() : '';
    div.innerHTML = `
      <div class="incident-type">🚨 ${escHtml(inc.type || 'INCIDENT')} <small style="opacity:.5">${ts}</small></div>
      <div class="incident-detail">${escHtml((inc.detail || inc.reason || '').slice(0, 120))}</div>
    `;
    list.appendChild(div);
    list.scrollTop = list.scrollHeight;
  });
}

// ── Report ─────────────────────────────────────────
let lastReport = '';

function renderReport(report) {
  if (!report || report === lastReport) return;
  lastReport = report;

  const body = document.getElementById('report-body');
  body.innerHTML = markdownToHtml(report);
  body.scrollTop = 0;
}

// ── Chips ──────────────────────────────────────────
function renderChips(state) {
  const phaseEl   = document.getElementById('chip-phase');
  const backendEl = document.getElementById('chip-backend');

  if (phaseEl)   phaseEl.textContent   = `PHASE: ${(state.pra_phase || 'IDLE').toUpperCase()}`;
  if (backendEl && state.agents?.supervisor?.metrics?.llm_backend) {
    backendEl.textContent = `LLM: ${state.agents.supervisor.metrics.llm_backend}`;
  }
}

// ── Task State ─────────────────────────────────────
function handleTaskState(state) {
  const phase = state.pra_phase || 'idle';
  const running = ['perception','reasoning','action'].includes(phase);
  if (!running && taskRunning) setTaskRunning(false);
}

function setTaskRunning(running) {
  taskRunning = running;
  const btn     = document.getElementById('btn-run');
  const btnText = document.getElementById('btn-run-text');
  if (btn) {
    btn.disabled = running;
    btn.classList.toggle('running', running);
  }
  if (btnText) btnText.textContent = running ? '⚡ Running...' : '▶ Run Task';
}

// ── Connection Status ──────────────────────────────
function setConnectionStatus(state) {
  const dot   = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');

  const states = {
    connecting:    ['', 'Connecting...'],
    connected:     ['connected', '● Connected'],
    disconnected:  ['disconnected', '✕ Disconnected — Retrying...'],
  };

  const [cls, text] = states[state] || ['', state];
  if (dot)   { dot.className = `status-dot ${cls}`; }
  if (label) { label.textContent = text; }
}

// ── Markdown-lite ──────────────────────────────────
function markdownToHtml(md) {
  return md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^## (.*)/gm,   '<h2>$1</h2>')
    .replace(/^### (.*)/gm,  '<h3>$1</h3>')
    .replace(/^#### (.*)/gm, '<h4>$1</h4>')
    .replace(/\*\*(.*?)\*\*/g,  '<strong>$1</strong>')
    .replace(/`([^`]+)`/g,      '<code>$1</code>')
    .replace(/^  • (.*)/gm,     '<li>$1</li>')
    .replace(/^\d+\. (.*)/gm,   '<li>$1</li>')
    .replace(/^---$/gm,         '<hr style="border-color:rgba(255,255,255,0.08);margin:1rem 0">')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/^(?!<[hplio])/gm, '')
    .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
}

// ── Utils ──────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
