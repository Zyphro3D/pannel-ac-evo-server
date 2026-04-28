/* ── CSRF helper ── */
function _csrfHeaders(extra) {
  const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
  return Object.assign({ 'Content-Type': 'application/json', 'X-CSRFToken': token }, extra);
}

/* ── Config check / repair ── */
async function checkConfig() {
  try {
    const r = await fetch('/api/config/check');
    const d = await r.json();
    if (!d.ok && d.issues && d.issues.length > 0) {
      const list = document.getElementById('modal-error-list');
      if (list) {
        list.innerHTML = '';
        d.issues.forEach(i => {
          const li = document.createElement('li');
          li.textContent = i;
          list.appendChild(li);
        });
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
  if (navLbl) navLbl.textContent = txt; // sera affiné par nav_label si dispo

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
    const navLbl = document.getElementById('status-label');
    if (navLbl && d.running && d.nav_label) navLbl.textContent = d.nav_label;
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

/* ── Sauvegarder tout (serveur + événement + sessions + véhicules) ── */
async function saveAll() {
  const data = {};

  // Section Serveur
  const formServer = document.getElementById('form-server');
  if (formServer) {
    for (const el of formServer.elements) {
      if (!el.name) continue;
      data[el.name] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
    }
  }

  // Section Événement
  const formEvent = document.getElementById('form-event');
  if (formEvent) {
    for (const el of formEvent.elements) {
      if (!el.name) continue;
      data[el.name] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
    }
  }

  // Section Sessions (champs imbriqués)
  const formSessions = document.getElementById('form-sessions');
  if (formSessions) {
    const sessions = {};
    for (const el of formSessions.elements) {
      if (!el.name) continue;
      const match = el.name.match(/^(\w+)\[(\w+)\]$/);
      if (!match) continue;
      const [, sessKey, field] = match;
      if (!sessions[sessKey]) sessions[sessKey] = {};
      sessions[sessKey][field] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
    }
    data.Sessions = sessions;
  }

  // Section Véhicules
  const allCars = [];
  document.querySelectorAll('.car-row').forEach(row => {
    const name = row.querySelector('.car-check')?.dataset.car;
    if (!name) return;
    const isSelected = row.querySelector('.car-check').checked;
    const ballast    = Number(row.querySelector('.car-ballast')?.value || 0);
    const restrictor = Number(row.querySelector('.car-restrictor')?.value || 0);
    allCars.push({ name, IsSelected: isSelected, is_selected: isSelected, Ballast: ballast, ballast, Restrictor: restrictor, restrictor });
  });
  if (allCars.length) data.Cars = allCars;

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

/* ── Duration widget ── */
function calcDur(key, widget) {
  const parts = widget.querySelectorAll('.dur-part');
  let h = parseInt(parts[0].value) || 0;
  let m = parseInt(parts[1].value) || 0;
  let s = parseInt(parts[2].value) || 0;
  let total = h * 3600 + m * 60 + s;
  if (total > 86400) {
    total = 86400;
    parts[0].value = 24; parts[1].value = 0; parts[2].value = 0;
  }
  const hidden = document.getElementById('dur-' + key);
  if (hidden) hidden.value = total;
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
function toggleCat(btn) {
  btn.classList.toggle('active');
  filterCars(true);
}

function updatePiSlider() {
  const minR = document.getElementById('pi-range-min');
  const maxR = document.getElementById('pi-range-max');
  if (!minR || !maxR) return;
  let minVal = parseFloat(minR.value);
  let maxVal = parseFloat(maxR.value);
  if (minVal > maxVal) {
    minR.value = maxVal; maxR.value = minVal;
    [minVal, maxVal] = [maxVal, minVal];
  }
  const lo = parseFloat(minR.min), hi = parseFloat(minR.max), span = hi - lo;
  const p1 = span > 0 ? ((minVal - lo) / span * 100) : 0;
  const p2 = span > 0 ? ((maxVal - lo) / span * 100) : 100;
  const track = document.getElementById('pi-slider-track');
  if (track) track.style.background =
    `linear-gradient(to right,var(--border) ${p1}%,var(--accent) ${p1}%,var(--accent) ${p2}%,var(--border) ${p2}%)`;
  const disp = document.getElementById('pi-display');
  if (disp) disp.textContent = `${minVal.toFixed(1)} — ${maxVal.toFixed(1)}`;
  filterCars(true);
}

// autoSelect=true : les filtres catégorie/PI cochent automatiquement les voitures visibles
//                   et décochez les cachées.
// autoSelect=false : la recherche texte et "sélectionnés seulement" filtrent la vue sans toucher aux coches.
function filterCars(autoSelect = false) {
  const search = (document.getElementById('car-search')?.value || '').toLowerCase();
  const showSelected = document.getElementById('show-selected-only')?.checked || false;
  const minR = document.getElementById('pi-range-min');
  const maxR = document.getElementById('pi-range-max');
  const piMin = minR ? parseFloat(minR.value) : 0;
  const piMax = maxR ? parseFloat(maxR.value) : 999;

  // Catégories : OR à l'intérieur de chaque colonne, AND entre colonnes.
  const COL = { Road:'p1',Race:'p1',Track:'p1', Modern:'p2',Vintage:'p2',YT:'p2', ICE:'p3',EV:'p3',Hybrid:'p3' };
  const active = { p1: new Set(), p2: new Set(), p3: new Set() };
  document.querySelectorAll('.cat-btn').forEach(btn => {
    const col = COL[btn.dataset.cat];
    if (col && btn.classList.contains('active')) active[col].add(btn.dataset.cat);
  });
  const colOk = (val, col) => active[col].size === 0 || !val || active[col].has(val);

  document.querySelectorAll('.car-row').forEach(row => {
    const name = row.dataset.name;
    const pi   = parseFloat(row.dataset.pi);
    const matchCat      = colOk(row.dataset.p1,'p1') && colOk(row.dataset.p2,'p2') && colOk(row.dataset.p3,'p3');
    const matchPi       = pi >= piMin && pi <= piMax;
    const matchSearch   = name.includes(search);
    const matchSelected = !showSelected || row.querySelector('.car-check')?.checked;
    const visible = matchCat && matchPi && matchSearch && matchSelected;
    row.classList.toggle('hidden', !visible);
    if (autoSelect) {
      const cb = row.querySelector('.car-check');
      if (cb) cb.checked = matchCat && matchPi; // sélection basée sur catégorie+PI uniquement (pas la recherche)
    }
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
  cb.addEventListener('change', () => { updateSelectedCount(); if (document.getElementById('show-selected-only')?.checked) filterCars(); });
});
updateSelectedCount();

// Init du slider PI (colore la plage dès le chargement)
(function () { if (document.getElementById('pi-range-min')) updatePiSlider(); })();

