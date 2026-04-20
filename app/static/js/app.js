/* ── Config check / repair ── */
async function checkConfig() {
  try {
    const r = await fetch('/api/config/check');
    const d = await r.json();
    if (!d.ok && d.issues && d.issues.length > 0) {
      const list = document.getElementById('modal-error-list');
      if (list) {
        list.innerHTML = d.issues.map(i => `<li>${i}</li>`).join('');
      }
      document.getElementById('modal-config-error').style.display = 'flex';
    }
  } catch (_) {}
}

function closeConfigErrorModal() {
  document.getElementById('modal-config-error').style.display = 'none';
}

async function doRepairConfig() {
  const r = await fetch('/api/config/repair', { method: 'POST' });
  const d = await r.json();
  if (d.ok) {
    closeConfigErrorModal();
    showToast(I18N.configRepaired, 'success');
    setTimeout(() => window.location.reload(), 800);
  } else {
    showToast(I18N.error, 'error');
  }
}

checkConfig();

/* ── Config file management ── */
async function switchConfig(name) {
  const r = await fetch('/api/configs/select', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const d = await r.json();
  if (d.ok) {
    window.location.reload();
  } else {
    showToast(I18N.error + ': ' + d.error, 'error');
  }
}

function openCreateModal(duplicate) {
  const active = document.getElementById('config-select')?.value || '';
  document.getElementById('modal-title').textContent = duplicate
    ? I18N.duplicateTitle
    : I18N.newConfigTitle;
  document.getElementById('modal-name').value = duplicate
    ? active.replace('.json', '') + '-copie.json'
    : '';
  document.getElementById('modal-copy-from').value = duplicate ? active : '';
  document.getElementById('modal-create').style.display = 'flex';
  setTimeout(() => document.getElementById('modal-name').focus(), 50);
}

function closeModal() {
  document.getElementById('modal-create').style.display = 'none';
}

async function submitCreate() {
  const name     = document.getElementById('modal-name').value.trim();
  const copyFrom = document.getElementById('modal-copy-from').value || null;
  if (!name) { showToast(I18N.nameRequired, 'error'); return; }

  const r = await fetch('/api/configs/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, copy_from: copyFrom }),
  });
  const d = await r.json();
  if (d.ok) {
    closeModal();
    // Sélectionner la nouvelle config puis recharger
    await fetch('/api/configs/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: d.name }),
    });
    window.location.reload();
  } else {
    showToast('Erreur: ' + d.error, 'error');
  }
}

async function confirmDeleteConfig() {
  const name = document.getElementById('config-select')?.value;
  if (!name) return;
  if (!confirm(`Supprimer "${name}" ? Cette action est irréversible.`)) return;

  const r = await fetch('/api/configs/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const d = await r.json();
  if (d.ok) {
    window.location.reload();
  } else {
    showToast('Erreur: ' + d.error, 'error');
  }
}

// Fermer modal en cliquant en dehors
document.getElementById('modal-create')?.addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

/* ── Tabs ── */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab)?.classList.add('active');
  });
});

/* ── Toast ── */
function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => { t.className = 'toast'; }, 3000);
}

/* ── Server status polling ── */
// Config active courante (injectée depuis le template)
const _activeConfig = document.body.dataset.activeConfig || '';

async function toggleAutoRestart(enabled) {
  const chk = document.getElementById('chk-auto-restart');
  if (!chk) return;
  try {
    const r = await fetch('/api/server/auto-restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    const d = await r.json();
    if (!d.ok) {
      chk.checked = !enabled;
      showToast(I18N.error + ': ' + (d.error || ''), 'error');
    } else {
      showToast(enabled ? I18N.autoRestartOn : I18N.autoRestartOff, 'success');
    }
  } catch (_) {
    chk.checked = !enabled;
    showToast(I18N.networkError, 'error');
  }
}

function updateStatusUI(running, runningConfig, autoRestart, players) {
  const sameConfig  = running && runningConfig === _activeConfig;
  const otherConfig = running && runningConfig !== _activeConfig;

  const dots      = document.querySelectorAll('.dot');
  const label     = document.getElementById('main-status-label');
  const navLbl    = document.getElementById('status-label');
  const playerEl  = document.getElementById('player-count');

  dots.forEach(d => {
    d.classList.toggle('online',  running);
    d.classList.toggle('offline', !running);
  });

  let txt = I18N.offline;
  if (sameConfig)   txt = I18N.online;
  if (otherConfig)  txt = `${I18N.online} (${runningConfig})`;
  if (label)  label.textContent  = txt;
  if (navLbl) navLbl.textContent = txt;

  if (playerEl) {
    playerEl.textContent = (running && players !== null && players !== undefined)
      ? `${players} ${I18N.players}`
      : '';
  }

  const btnStart   = document.getElementById('btn-start');
  const btnStop    = document.getElementById('btn-stop');
  const btnRestart = document.getElementById('btn-restart');

  // Start : visible si serveur OFF ou si c'est une autre config qui tourne
  if (btnStart)   { btnStart.disabled   = sameConfig;  btnStart.style.display   = sameConfig  ? 'none' : ''; }
  // Stop + Restart : visibles uniquement si CE config tourne
  if (btnStop)    { btnStop.disabled    = !sameConfig; btnStop.style.display    = sameConfig  ? ''     : 'none'; }
  if (btnRestart) { btnRestart.disabled = !sameConfig; btnRestart.style.display = sameConfig  ? ''     : 'none'; }

  const chk = document.getElementById('chk-auto-restart');
  if (chk) chk.checked = !!autoRestart;
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    updateStatusUI(d.running, d.config, d.auto_restart, d.players);
  } catch (_) {}
}

fetchStatus();
setInterval(fetchStatus, 5000);

/* ── Server logs ── */
async function loadLogs() {
  const pre = document.getElementById('logs-content');
  try {
    const r = await fetch('/api/server/logs');
    const d = await r.json();
    pre.textContent = d.logs || '(vide)';
    pre.scrollTop = pre.scrollHeight;
  } catch (_) {
    pre.textContent = 'Erreur de chargement';
  }
}

function openLogs() {
  document.getElementById('modal-logs').style.display = 'flex';
  loadLogs();
}

/* ── Server start/stop ── */
const _serverBtns = () => ['start','stop','restart'].map(id => document.getElementById(`btn-${id}`));

async function serverAction(action) {
  _serverBtns().forEach(b => { if (b) b.disabled = true; });

  const labels = { start: I18N.serverStarted, stop: I18N.serverStopped, restart: I18N.serverRestarted };
  try {
    const r = await fetch(`/api/server/${action}`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      showToast(labels[action] || 'OK', 'success');
      setTimeout(fetchStatus, 1500);
    } else {
      const msg = d.detail || d.error || I18N.error;
      showToast(msg, 'error');
      setTimeout(fetchStatus, 500);
    }
  } catch (e) {
    showToast('Erreur réseau', 'error');
    setTimeout(fetchStatus, 500);
  }
}

/* ── Save server / event sections ── */
async function saveSection(formId) {
  const form = document.getElementById(formId);
  const data = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') {
      data[el.name] = el.checked;
    } else if (el.type === 'number') {
      data[el.name] = Number(el.value);
    } else {
      data[el.name] = el.value;
    }
  }
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const d = await r.json();
    showToast(d.ok ? I18N.saved : I18N.error, d.ok ? 'success' : 'error');
  } catch (_) {
    showToast(I18N.networkError, 'error');
  }
}

/* ── Save event + sessions (onglet fusionné) ── */
async function saveEventAndSessions() {
  const data = {};

  // Champs événement (flat)
  for (const el of document.getElementById('form-event').elements) {
    if (!el.name) continue;
    data[el.name] = el.type === 'checkbox' ? el.checked
                  : el.type === 'number'   ? Number(el.value)
                  : el.value;
  }

  // Champs sessions (imbriqués)
  const sessions = {};
  for (const el of document.getElementById('form-sessions').elements) {
    if (!el.name) continue;
    const match = el.name.match(/^(\w+)\[(\w+)\]$/);
    if (!match) continue;
    const [, sessKey, field] = match;
    if (!sessions[sessKey]) sessions[sessKey] = {};
    sessions[sessKey][field] = el.type === 'checkbox' ? el.checked
                             : el.type === 'number'   ? Number(el.value)
                             : el.value;
  }
  data.Sessions = sessions;

  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const d = await r.json();
    showToast(d.ok ? I18N.saved : I18N.error, d.ok ? 'success' : 'error');
  } catch (_) {
    showToast(I18N.networkError, 'error');
  }
}

/* ── Save sessions ── */
async function saveSessions() {
  const form = document.getElementById('form-sessions');
  const sessions = {};

  for (const el of form.elements) {
    if (!el.name) continue;
    const match = el.name.match(/^(\w+)\[(\w+)\]$/);
    if (!match) continue;
    const [, sessKey, field] = match;
    if (!sessions[sessKey]) sessions[sessKey] = {};
    if (el.type === 'checkbox') {
      sessions[sessKey][field] = el.checked;
    } else if (el.type === 'number') {
      sessions[sessKey][field] = Number(el.value);
    } else {
      sessions[sessKey][field] = el.value;
    }
  }

  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ Sessions: sessions }),
    });
    const d = await r.json();
    showToast(d.ok ? I18N.sessionsSaved : I18N.error, d.ok ? 'success' : 'error');
  } catch (_) {
    showToast(I18N.networkError, 'error');
  }
}

/* ── Session type toggle ── */
function onSessionTypeChange(val) {
  const isRaceWeekend = val === 'GameModeType_RACE_WEEKEND';
  document.querySelectorAll('.sess-race-only').forEach(el => {
    el.style.display = isRaceWeekend ? '' : 'none';
  });
}

// Init au chargement
(function() {
  const sel = document.getElementById('session-type-select');
  if (sel) onSessionTypeChange(sel.value);
})();

/* ── Cars ── */
function filterCars() {
  const search = (document.getElementById('car-search')?.value || '').toLowerCase();
  const piMin  = parseFloat(document.getElementById('pi-min')?.value) || 0;
  const piMax  = parseFloat(document.getElementById('pi-max')?.value) || 999;

  document.querySelectorAll('.car-row').forEach(row => {
    const name = row.dataset.name.toLowerCase();
    const pi   = parseFloat(row.dataset.pi);
    const match = name.includes(search) && pi >= piMin && pi <= piMax;
    row.classList.toggle('hidden', !match);
  });
  updateSelectedCount();
}

function selectAllVisible(checked) {
  document.querySelectorAll('.car-row:not(.hidden) .car-check').forEach(cb => {
    cb.checked = checked;
  });
  updateSelectedCount();
}

function updateSelectedCount() {
  const total = document.querySelectorAll('.car-check:checked').length;
  const el = document.getElementById('cars-selected-count');
  if (el) el.textContent = `${total} véhicule(s) sélectionné(s)`;
}

document.querySelectorAll('.car-check').forEach(cb => {
  cb.addEventListener('change', updateSelectedCount);
});
updateSelectedCount();

async function saveCars() {
  const allCars = [];
  document.querySelectorAll('.car-row').forEach(row => {
    const name = row.querySelector('.car-check')?.dataset.car;
    if (!name) return;
    const isSelected = row.querySelector('.car-check').checked;
    const ballast    = Number(row.querySelector('.car-ballast')?.value || 0);
    const restrictor = Number(row.querySelector('.car-restrictor')?.value || 0);

    allCars.push({
      name,
      IsSelected: isSelected,
      is_selected: isSelected,
      Ballast: ballast,
      ballast,
      Restrictor: restrictor,
      restrictor,
    });
  });

  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ Cars: allCars }),
    });
    const d = await r.json();
    showToast(d.ok ? I18N.carsSaved : I18N.error, d.ok ? 'success' : 'error');
  } catch (_) {
    showToast(I18N.networkError, 'error');
  }
}
