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
  const r = await fetch('/api/config/repair', { method: 'POST', headers: _csrfHeaders() });
  const d = await r.json();
  if (d.ok) {
    closeConfigErrorModal();
    showToast(I18N.configRepaired, 'success');
    setTimeout(() => window.location.reload(), 800);
  } else {
    showToast(I18N.error, 'error');
  }
}

if (document.getElementById('modal-config-error')) checkConfig();

/* ── Config file management ── */
async function switchConfig(name) {
  const r = await fetch('/api/configs/select', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ name }),
  });
  const d = await r.json();
  if (d.ok) {
    window.location.reload();
  } else {
    showToast(I18N.error + ': ' + d.error, 'error');
  }
}

async function editConfig(name, editUrl) {
  const r = await fetch('/api/configs/select', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ name }),
  });
  const d = await r.json();
  if (d.ok) {
    window.location.href = editUrl;
  } else {
    showToast(I18N.error + ': ' + d.error, 'error');
  }
}

async function startConfig(name) {
  let statusData = null;
  try {
    const sr = await fetch('/api/status');
    statusData = await sr.json();
  } catch (_) {}

  if (statusData && statusData.running && statusData.config && statusData.config !== name) {
    const ok = await showConfirm(
      (I18N.serverRunningWith || 'Le serveur tourne avec') + ' « ' + statusData.config + ' ».\n' +
      (I18N.replaceWith || 'Remplacer par') + ' « ' + name + ' » ?'
    );
    if (!ok) return;
  }

  const sel = await fetch('/api/configs/select', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ name }),
  });
  if (!(await sel.json()).ok) { showToast(I18N.error, 'error'); return; }

  const start = await fetch('/api/server/start', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({}),
  });
  const d = await start.json();
  if (d.ok) {
    showToast(I18N.serverStarted, 'success');
    setTimeout(() => window.location.reload(), 1500);
  } else {
    showToast(I18N.error + ': ' + (d.error || ''), 'error');
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
  window.dispatchEvent(new CustomEvent('open-modal-create'));
  setTimeout(() => document.getElementById('modal-name').focus(), 50);
}

function closeModal() {
  window.dispatchEvent(new CustomEvent('close-modal-create'));
}

async function submitCreate() {
  const name     = document.getElementById('modal-name').value.trim();
  const copyFrom = document.getElementById('modal-copy-from').value || null;
  if (!name) { showToast(I18N.nameRequired, 'error'); return; }

  const r = await fetch('/api/configs/create', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ name, copy_from: copyFrom }),
  });
  const d = await r.json();
  if (d.ok) {
    closeModal();
    // Sélectionner la nouvelle config puis recharger
    await fetch('/api/configs/select', {
      method: 'POST',
      headers: _csrfHeaders(),
      body: JSON.stringify({ name: d.name }),
    });
    window.location.reload();
  } else {
    showToast(I18N.error + ': ' + d.error, 'error');
  }
}

async function confirmDeleteConfig() {
  const name = document.getElementById('config-select')?.value;
  if (!name) return;
  if (!await showConfirm(I18N.confirmDeleteConfig.replace('%s', name))) return;

  const r = await fetch('/api/configs/delete', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ name }),
  });
  const d = await r.json();
  if (d.ok) {
    window.location.reload();
  } else {
    showToast(I18N.error + ': ' + d.error, 'error');
  }
}

function openRenameModal() {
  const current = document.getElementById('config-select')?.value;
  if (!current) return;
  document.getElementById('modal-rename-old').value = current;
  document.getElementById('modal-rename-new').value = current.replace(/\.json$/i, '');
  window.dispatchEvent(new CustomEvent('open-modal-rename'));
  setTimeout(() => document.getElementById('modal-rename-new').select(), 50);
}
function closeRenameModal() {
  window.dispatchEvent(new CustomEvent('close-modal-rename'));
}
async function submitRename() {
  const oldName = document.getElementById('modal-rename-old').value;
  const newName = document.getElementById('modal-rename-new').value.trim();
  if (!newName) return;
  const r = await fetch('/api/configs/rename', {
    method: 'POST',
    headers: _csrfHeaders(),
    body: JSON.stringify({ old_name: oldName, new_name: newName }),
  });
  const d = await r.json();
  if (d.ok) { window.location.reload(); }
  else { showToast(I18N.error + ': ' + d.error, 'error'); }
}

// Fermer modal-config-error en cliquant en dehors (non géré par Alpine)
document.getElementById('modal-config-error')?.addEventListener('click', function(e) {
  if (e.target === this) closeConfigErrorModal();
});


/* ── Toast ── */
function showToast(msg, type = 'success') {
  const zone = document.getElementById('toast-zone');
  if (!zone) return;
  const div = document.createElement('div');
  div.innerHTML = `<div x-data="{ show: true }"
    x-show="show" x-init="setTimeout(() => show = false, 4500)" x-transition
    class="toast toast-${type}" role="alert" aria-live="polite">
    <span></span>
    <button @click="show = false" class="toast-close" aria-label="Fermer">✕</button>
  </div>`;
  const el = div.firstElementChild;
  el.querySelector('span').textContent = msg;
  zone.prepend(el);
  if (window.Alpine) Alpine.initTree(zone.firstElementChild);
}

/* ── Server status polling ── */
// Config active courante (injectée depuis le template)
const _activeConfig = document.body.dataset.activeConfig || '';

async function toggleAutoRestart(enabled) {
  // Deux checkboxes possibles selon la page (barre de contrôle / widget statut) —
  // ne jamais dépendre de la présence d'une seule des deux pour continuer.
  const checkboxes = ['chk-auto-restart', 'srv-auto-restart-card']
    .map(id => document.getElementById(id))
    .filter(Boolean);
  const label = document.getElementById('srv-auto-restart-label');

  const syncUI = (value) => {
    checkboxes.forEach(chk => { chk.checked = value; });
    if (label) label.textContent = value ? I18N.autoRestartOn : I18N.autoRestartOff;
  };

  try {
    const r = await fetch('/api/server/auto-restart', {
      method: 'POST',
      headers: _csrfHeaders(),
      body: JSON.stringify({ enabled }),
    });
    const d = await r.json();
    if (!d.ok) {
      syncUI(!enabled);
      showToast(I18N.error + ': ' + (d.error || ''), 'error');
    } else {
      syncUI(enabled);
      showToast(enabled ? I18N.autoRestartOn : I18N.autoRestartOff, 'success');
    }
  } catch (_) {
    syncUI(!enabled);
    showToast(I18N.networkError, 'error');
  }
}

function updateStatusUI(running, runningConfig, autoRestart, players, rotationCountdown) {
  const wasRunning = _serverRunning;
  _serverRunning = !!running;

  // Dirty banner : cacher quand le serveur s'arrête ou vient réellement de (re)démarrer
  // (wasRunning === false, pas null — sinon le tout premier poll après chargement de
  // page la cachait systématiquement, même quand elle devait rester visible), et
  // l'afficher dès qu'on détecte en direct que la config qui tourne diffère de celle
  // sélectionnée dans le panel.
  const banner = document.getElementById('config-dirty-banner');
  if (banner) {
    if (!running || (wasRunning === false && running)) {
      banner.style.display = 'none';
    } else if (running && runningConfig && runningConfig !== _activeConfig) {
      banner.style.display = '';
    }
  }

  // Compte à rebours avant le prochain changement de config par inactivité :
  // ancré sur une échéance absolue (recalée à chaque poll) plutôt que sur le
  // countdown brut, pour un tick fluide à la seconde entre deux polls de 5s.
  _rotCountdownDeadline = (rotationCountdown === null || rotationCountdown === undefined)
    ? null
    : (Date.now() / 1000 + rotationCountdown);
  _tickRotCountdown();

  _rotIsRunning  = !!running;
  _rotRunningCfg = runningConfig || '';
  updateRotationStatus();
  const sameConfig  = running && runningConfig === _activeConfig;
  const otherConfig = running && runningConfig !== _activeConfig;

  // Only update server-status dots (not the timing widget dot)
  const statusDotIds = ['main-status-dot', 'status-dot'];
  statusDotIds.forEach(id => {
    const d = document.getElementById(id);
    if (d) {
      d.classList.toggle('online',  running);
      d.classList.toggle('offline', !running);
    }
  });

  let txt = running ? I18N.online : I18N.offline;
  const label    = document.getElementById('main-status-label');
  const navLbl   = document.getElementById('status-label');
  const sideLbl  = document.getElementById('server-side-status');
  const playerEl = document.getElementById('player-count');
  const playerNum = document.getElementById('player-count-number');
  const playerSb = document.getElementById('player-count-sb');
  if (label)  label.textContent  = txt;
  if (navLbl) navLbl.textContent = txt;
  if (sideLbl) sideLbl.textContent = txt;

  const pTxt = (running && players !== null && players !== undefined)
    ? `${players} ${I18N.players}` : '';
  if (playerEl) playerEl.textContent = pTxt;
  if (playerNum) playerNum.textContent = (running && players !== null && players !== undefined) ? players : '0';
  if (playerSb) playerSb.textContent = pTxt;

  const btnStart   = document.getElementById('btn-start');
  const btnStop    = document.getElementById('btn-stop');
  const btnRestart = document.getElementById('btn-restart');

  // Réactiver tous les boutons et restaurer leur label d'origine
  [btnStart, btnStop, btnRestart].forEach(b => {
    if (!b) return;
    b.disabled = false;
    if (b.dataset.origLabel) {
      const strong = b.querySelector('strong');
      (strong || b).textContent = b.dataset.origLabel;
      delete b.dataset.origLabel;
    }
  });

  const editMode = document.getElementById('server-control')?.dataset.barMode === 'edit';
  if (editMode) {
    // Page config_edit : les boutons dépendent du fait que CETTE config tourne
    if (btnStart)   { btnStart.style.display   = sameConfig ? 'none' : ''; }
    if (btnStop)    { btnStop.style.display     = sameConfig ? ''     : 'none'; }
    if (btnRestart) { btnRestart.style.display  = sameConfig ? ''     : 'none'; }
  } else {
    // Comportement standard (vue statut, etc.)
    if (btnStart)   { btnStart.style.display   = running ? 'none' : ''; }
    if (btnStop)    { btnStop.style.display     = running ? ''     : 'none'; }
    if (btnRestart) { btnRestart.style.display  = running ? ''     : 'none'; }
  }

  const chk = document.getElementById('chk-auto-restart');
  if (chk) chk.checked = !!autoRestart;

  const chkCard = document.getElementById('srv-auto-restart-card');
  const lblCard = document.getElementById('srv-auto-restart-label');
  if (chkCard) chkCard.checked = !!autoRestart;
  if (lblCard) lblCard.textContent = autoRestart ? I18N.autoRestartOn : I18N.autoRestartOff;
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    updateStatusUI(d.running, d.config, d.auto_restart, d.players, d.rotation_countdown);
    if (typeof window._onPublicStatusUpdate === 'function') window._onPublicStatusUpdate(d);
  } catch (_) {}
}

if (document.getElementById('main-status-dot') || document.getElementById('status-dot') || document.getElementById('server-side-status')) {
  fetchStatus();
  setInterval(fetchStatus, 5000);
}

/* ── Server logs ── */
async function loadLogs() {
  const pre = document.getElementById('logs-content');
  try {
    const r = await fetch('/api/server/logs');
    const d = await r.json();
    pre.textContent = d.logs || (I18N.empty || '(vide)');
    pre.scrollTop = pre.scrollHeight;
  } catch (_) {
    pre.textContent = I18N.loadError || I18N.error;
  }
}

function openLogs() {
  window.dispatchEvent(new CustomEvent('open-modal-logs'));
  loadLogs();
}

/* ── Server start/stop ── */
const _serverBtns = () => ['start','stop','restart'].map(id => document.getElementById(`btn-${id}`));

async function serverAction(action) {
  if (action === 'stop'    && !await showConfirm(I18N.confirmStop))    return;
  if (action === 'restart' && !await showConfirm(I18N.confirmRestart)) return;

  const loadingLabel = { start: I18N.serverStarting, stop: I18N.serverStopping, restart: I18N.serverRestarting };
  _serverBtns().forEach(b => {
    if (!b) return;
    b.disabled = true;
    if (b.id === `btn-${action}`) {
      const strong = b.querySelector('strong');
      const target = strong || b;
      if (!b.dataset.origLabel) b.dataset.origLabel = target.textContent;
      target.textContent = loadingLabel[action] || '…';
    }
  });

  const labels = { start: I18N.serverStarted, stop: I18N.serverStopped, restart: I18N.serverRestarted };
  try {
    const r = await fetch(`/api/server/${action}`, { method: 'POST', headers: _csrfHeaders() });
    const d = await r.json();
    if (d.ok) {
      showToast(labels[action] || 'OK', 'success');
      // Polls successifs : le container Docker met quelques secondes à démarrer/s'arrêter
      [1000, 3000, 6000, 10000].forEach(ms => setTimeout(fetchStatus, ms));
    } else {
      const msg = d.detail || d.error || I18N.error;
      showToast(msg, 'error');
      setTimeout(fetchStatus, 800);
    }
  } catch (e) {
    showToast(I18N.networkError, 'error');
    setTimeout(fetchStatus, 800);
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
      const _isNum = el.type === 'number' || (el.tagName === 'SELECT' && el.value !== '' && !isNaN(el.value));
      sessions[sessKey][field] = el.type === 'checkbox' ? el.checked : _isNum ? Number(el.value) : el.value;
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
      headers: _csrfHeaders(),
      body: JSON.stringify(data),
    });
    const d = await r.json();
    if (d.ok) {
      showToast(I18N.saved, 'success');
      const banner = document.getElementById('config-dirty-banner');
      if (banner && _serverRunning) banner.style.display = '';
    } else {
      showToast(I18N.error, 'error');
    }
  } catch (_) {
    showToast(I18N.networkError, 'error');
  }
}

/* ── PI slider ── */
function updatePiSlider(autoSelect = true) {
  const minR = document.getElementById('pi-range-min');
  const maxR = document.getElementById('pi-range-max');
  if (!minR || !maxR) return;
  let minVal = parseFloat(minR.value);
  let maxVal = parseFloat(maxR.value);
  if (minVal > maxVal) {
    minR.value = maxVal; maxR.value = minVal;
    [minVal, maxVal] = [maxVal, minVal];
  }
  localStorage.setItem('sv_pi_min', minVal);
  localStorage.setItem('sv_pi_max', maxVal);
  const lo = parseFloat(minR.min), hi = parseFloat(minR.max), span = hi - lo;
  const p1 = span > 0 ? ((minVal - lo) / span * 100) : 0;
  const p2 = span > 0 ? ((maxVal - lo) / span * 100) : 100;
  const track = document.getElementById('pi-slider-track');
  if (track) track.style.background =
    `linear-gradient(to right,rgba(100,116,139,0.65) ${p1}%,var(--accent) ${p1}%,var(--accent) ${p2}%,rgba(100,116,139,0.65) ${p2}%)`;
  const disp = document.getElementById('pi-display');
  if (disp) disp.textContent = `${minVal.toFixed(1)} — ${maxVal.toFixed(1)}`;
  filterCars(autoSelect);
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
// Modes dont la durée et l'heure sont imposées par le jeu (vérifié : aucun réglage ne les modifie)
const FIXED_MODES = ['GameModeType_HOTLAP', 'GameModeType_RALLY', 'GameModeType_A_TO_B', 'GameModeType_TEST_DRIVE'];

function onSessionTypeChange(val) {
  const weekend = val === 'GameModeType_RACE_WEEKEND';
  const instant = val === 'GameModeType_INSTANT_RACE';
  const fixed   = FIXED_MODES.includes(val);
  // Blocs de session visibles selon le mode : week-end = les quatre ; course instantanée = la course ;
  // modes à durée fixe = aucun ; libre / autre = la session libre.
  const visible = {
    practicesession:   !(instant || fixed),
    qualifyingsession: weekend,
    warmupsession:     weekend,
    racesession:       weekend || instant,
  };
  Object.entries(visible).forEach(([key, show]) => {
    const el = document.getElementById('sess-' + key);
    if (!el) return;
    el.style.display = show ? '' : 'none';
    el.classList.toggle('enabled', show);
  });
  const note = document.getElementById('mode-fixed-note');
  if (note) note.style.display = fixed ? '' : 'none';
}

/* ── Avertissement : moins de stands que de joueurs ── */
function updatePitWarning() {
  const sel = document.getElementById('track-select');
  const warn = document.getElementById('pit-warning');
  if (!sel || !warn) return;
  const pits = parseInt((sel.selectedOptions[0] || {}).dataset?.pits || '0', 10);
  const max = parseInt(sel.dataset.maxPlayers || '0', 10);
  if (pits > 0 && max > pits) {
    warn.textContent = (warn.dataset.msg || '').replace('{pits}', pits).replace('{max}', max);
    warn.style.display = '';
  } else {
    warn.style.display = 'none';
  }
}

// Init au chargement
(function() {
  const sel = document.getElementById('session-type-select');
  if (sel) onSessionTypeChange(sel.value);
  updatePitWarning();
})();

/* ── Cars ── */
let _carSortDir = 'none';

function togglePiSort(th) {
  const dirs = ['none', 'asc', 'desc'];
  _carSortDir = dirs[(dirs.indexOf(_carSortDir) + 1) % dirs.length];
  const icon = document.getElementById('pi-sort-icon');
  if (icon) icon.textContent = _carSortDir === 'asc' ? '↑' : _carSortDir === 'desc' ? '↓' : '⇅';
  if (th) th.classList.toggle('pi-sort-active', _carSortDir !== 'none');
  _applyCarsSort();
}

function _applyCarsSort() {
  const tbody = document.querySelector('#cars-table tbody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('.car-row'));
  if (_carSortDir === 'asc') {
    rows.sort((a, b) => parseFloat(a.dataset.pi) - parseFloat(b.dataset.pi));
  } else if (_carSortDir === 'desc') {
    rows.sort((a, b) => parseFloat(b.dataset.pi) - parseFloat(a.dataset.pi));
  } else {
    rows.sort((a, b) => parseInt(a.dataset.idx) - parseInt(b.dataset.idx));
  }
  rows.forEach(r => tbody.appendChild(r));
}

function toggleCat(btn) {
  btn.classList.toggle('active');
  filterCars(true);
}

// autoSelect=true : les filtres catégorie/PI cochent automatiquement les voitures visibles
//                   et décochez les cachées.
// autoSelect=false : la recherche texte et "sélectionnés seulement" filtrent la vue sans toucher aux coches.
function filterCars(autoSelect = false) {
  const search = (document.getElementById('car-search')?.value || '').toLowerCase();
  const showSelected = document.getElementById('show-selected-only')?.checked || false;
  const officialOnly = document.getElementById('show-official-only')?.checked || false;
  const modsOnly     = document.getElementById('show-mods-only')?.checked || false;
  const minR = document.getElementById('pi-range-min');
  const maxR = document.getElementById('pi-range-max');
  const piMin = minR ? parseFloat(minR.value) : 0;
  const piMax = maxR ? parseFloat(maxR.value) : 999;

  // Catégories : OR global — la voiture s'affiche si l'un de ses badges est actif.
  const activeSet = new Set();
  document.querySelectorAll('.cat-btn.active').forEach(btn => {
    if (btn.dataset.cat) activeSet.add(btn.dataset.cat);
  });

  document.querySelectorAll('.car-row').forEach(row => {
    const name = row.dataset.name;
    const pi   = parseFloat(row.dataset.pi);
    const matchCat = activeSet.size === 0 ||
      [row.dataset.p1, row.dataset.p2, row.dataset.p3].some(v => v && activeSet.has(v));
    const matchPi       = pi >= piMin && pi <= piMax;
    const matchSearch   = name.includes(search);
    const matchSelected = !showSelected || row.querySelector('.car-check')?.checked;
    const matchOfficial = !officialOnly || row.dataset.ismod !== '1';
    const matchMods     = !modsOnly || row.dataset.ismod === '1';
    const visible = matchCat && matchPi && matchSearch && matchSelected && matchOfficial && matchMods;
    row.classList.toggle('hidden', !visible);
    if (autoSelect) {
      const cb = row.querySelector('.car-check');
      if (cb) cb.checked = matchCat && matchPi && matchOfficial && matchMods; // sélection basée sur catégorie+PI+officiel/mods (pas la recherche)
    }
  });
  updateSelectedCount();
  _applyCarsSort();
}

function selectAllVisible(checked) {
  document.querySelectorAll('.car-row:not(.hidden) .car-check').forEach(cb => {
    cb.checked = checked;
  });
  updateSelectedCount();
}

function deselectAll() {
  // Contrairement à selectAllVisible(false), désélectionne aussi les véhicules
  // masqués par le filtre/la recherche en cours — "tout désélectionner" doit
  // vider toute la sélection, pas seulement ce qui est actuellement visible.
  document.querySelectorAll('.car-check').forEach(cb => {
    cb.checked = false;
  });
  updateSelectedCount();
}

function updateSelectedCount() {
  const total = document.querySelectorAll('.car-check:checked').length;
  const el = document.getElementById('cars-selected-count');
  if (el) el.textContent = `${total} ${I18N.selectedVehicles || 'véhicule(s) sélectionné(s)'}`;
}

document.querySelectorAll('.car-check').forEach(cb => {
  cb.addEventListener('change', () => { updateSelectedCount(); if (document.getElementById('show-selected-only')?.checked) filterCars(); });
});
updateSelectedCount();

// Init du slider PI : restaure depuis localStorage sans toucher aux sélections sauvegardées.
// Un filtre PI sauvegardé peut devenir plus étroit que la plage réelle avec le temps (nouveau
// mod ajouté avec un PI plus haut/bas que tout ce qui existait au moment de la sauvegarde) —
// on élargit alors la plage restaurée pour ne jamais masquer une voiture déjà sélectionnée
// dans la config, sans quoi elle deviendrait invisible et impossible à désélectionner/vérifier.
(function () {
  const minR = document.getElementById('pi-range-min');
  const maxR = document.getElementById('pi-range-max');
  if (!minR || !maxR) return;
  const lo = parseFloat(minR.min), hi = parseFloat(minR.max);
  const savedMin = localStorage.getItem('sv_pi_min');
  const savedMax = localStorage.getItem('sv_pi_max');
  let minVal = savedMin !== null ? parseFloat(savedMin) : lo;
  let maxVal = savedMax !== null ? parseFloat(savedMax) : hi;
  // Clamp dans la plage actuelle (des voitures ont pu disparaître depuis la sauvegarde)
  minVal = Math.max(lo, Math.min(minVal, hi));
  maxVal = Math.max(lo, Math.min(maxVal, hi));
  // L'affichage arrondit à 1 décimale (pi-display) — si la valeur restaurée arrondit déjà
  // au même chiffre que la vraie borne, on "snap" dessus. Sans ça l'utilisateur peut voir
  // "82.0" affiché alors que la valeur réelle est 81.994 et rester bloqué en dessous du PI
  // exact d'un mod récemment ajouté, sans aucun moyen visuel de s'en rendre compte.
  if (Math.round((minVal - lo) * 10) === 0) minVal = lo;
  if (Math.round((hi - maxVal) * 10) === 0) maxVal = hi;
  document.querySelectorAll('.car-check:checked').forEach(cb => {
    const pi = parseFloat(cb.closest('.car-row')?.dataset.pi);
    if (!isNaN(pi)) {
      if (pi < minVal) minVal = pi;
      if (pi > maxVal) maxVal = pi;
    }
  });
  minR.value = minVal;
  maxR.value = maxVal;
  updatePiSlider(false);
})();

/* ── Roulement de configurations ── */
let _serverRunning = null; // null = pas encore observé (premier poll après chargement de page)
let _rotConfigs    = [];
let _rotIsRunning  = false;
let _rotRunningCfg = '';
let _rotCountdownDeadline = null;  // epoch (secondes) — null si non applicable

function _fmtRotCountdown(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
}

function _tickRotCountdown() {
  const el = document.getElementById('rot-idle-countdown');
  if (!el) return;
  if (_rotCountdownDeadline === null) {
    el.style.display = 'none';
    return;
  }
  el.style.display = '';
  const remaining = Math.max(0, Math.floor(_rotCountdownDeadline - Date.now() / 1000));
  el.textContent = (I18N.rotNextConfigIn || 'Prochaine config dans') + ' ' + _fmtRotCountdown(remaining);
}
setInterval(_tickRotCountdown, 1000);

function updateRotationStatus() {
  const enabled     = document.getElementById('rot-enabled')?.checked || false;
  const hasCycle    = document.getElementById('rot-cycle')?.checked   || false;
  const cycleActive = _rotIsRunning && _rotConfigs.includes(_rotRunningCfg);

  // Surligner le fichier en cours dans la liste
  document.querySelectorAll('#rot-list .rot-item').forEach((item, idx) => {
    item.classList.toggle('rot-item-active', cycleActive && _rotConfigs[idx] === _rotRunningCfg);
  });

  // Pilule de statut "en cours → suivant"
  const pill = document.getElementById('rot-status-pill');
  const txt  = document.getElementById('rot-status-text');
  if (pill) pill.style.display = cycleActive ? '' : 'none';
  if (txt && cycleActive) {
    const curIdx  = _rotConfigs.indexOf(_rotRunningCfg);
    const nextIdx = curIdx + 1;
    const nextCfg = nextIdx < _rotConfigs.length
      ? _rotConfigs[nextIdx]
      : (hasCycle ? _rotConfigs[0] : null);
    txt.textContent = _rotRunningCfg + (nextCfg ? '  →  ' + nextCfg : '  ' + I18N.rotLast);
  }

  // Boutons Start / Stop cycle
  const btnStart = document.getElementById('btn-start-cycle');
  const btnStop  = document.getElementById('btn-stop-cycle');
  if (btnStart) btnStart.style.display = (!cycleActive && enabled && _rotConfigs.length > 0) ? '' : 'none';
  if (btnStop)  btnStop.style.display  = cycleActive ? '' : 'none';
}

async function loadRotation() {
  try {
    const r = await fetch('/api/rotation');
    const d = await r.json();
    _rotConfigs = d.configs || [];
    const chkEnabled  = document.getElementById('rot-enabled');
    const chkCycle    = document.getElementById('rot-cycle');
    const idleTimeout = document.getElementById('rot-idle-timeout');
    if (chkEnabled)  chkEnabled.checked  = !!d.enabled;
    if (chkCycle)    chkCycle.checked    = !!d.cycle;
    if (idleTimeout) idleTimeout.value   = d.idle_timeout_minutes || 0;
    renderRotList();
    updateRotationStatus();
  } catch (_) {}
}

function onRotEnabledChange() {
  saveRotation();
  updateRotationStatus();
}

function renderRotList() {
  const list = document.getElementById('rot-list');
  if (!list) return;
  list.innerHTML = '';
  if (_rotConfigs.length === 0) {
    const p = document.createElement('p');
    p.className = 'rot-empty';
    p.textContent = I18N.rotationEmpty || 'Aucune configuration dans le roulement.';
    list.appendChild(p);
    updateRotationStatus();
    return;
  }
  _rotConfigs.forEach((cfg, idx) => {
    const isActive = _rotIsRunning && cfg === _rotRunningCfg;
    const item = document.createElement('div');
    item.className = 'rot-item' + (isActive ? ' rot-item-active' : '');
    item.innerHTML =
      `<span class="rot-item-pos">${idx + 1}</span>` +
      `<span class="rot-item-name">${cfg}</span>` +
      `<div class="rot-item-actions">` +
        `<button class="rot-btn" onclick="rotMove(${idx},-1)" ${idx === 0 ? 'disabled' : ''}>↑</button>` +
        `<button class="rot-btn" onclick="rotMove(${idx},1)" ${idx === _rotConfigs.length - 1 ? 'disabled' : ''}>↓</button>` +
        `<button class="rot-btn rot-btn-del" onclick="rotRemove(${idx})"><span class="icon-trash"></span></button>` +
      `</div>`;
    list.appendChild(item);
  });
  updateRotationStatus();
}

function rotAddConfig() {
  const sel = document.getElementById('rot-add-select');
  if (!sel || !sel.value) return;
  _rotConfigs.push(sel.value);
  renderRotList();
  saveRotation();
}

function rotMove(idx, dir) {
  const newIdx = idx + dir;
  if (newIdx < 0 || newIdx >= _rotConfigs.length) return;
  [_rotConfigs[idx], _rotConfigs[newIdx]] = [_rotConfigs[newIdx], _rotConfigs[idx]];
  renderRotList();
  saveRotation();
}

function rotRemove(idx) {
  _rotConfigs.splice(idx, 1);
  renderRotList();
  saveRotation();
}

async function startRotationCycle() {
  const btn = document.getElementById('btn-start-cycle');
  if (btn) btn.disabled = true;
  _serverBtns().forEach(b => { if (b) b.disabled = true; });
  try {
    const r = await fetch('/api/rotation/start', { method: 'POST', headers: _csrfHeaders() });
    const d = await r.json();
    if (d.ok) {
      showToast(I18N.cycleStarted || 'Cycle démarré', 'success');
      [1000, 3000, 6000, 10000].forEach(ms => setTimeout(fetchStatus, ms));
    } else {
      showToast(d.error || I18N.error, 'error');
      setTimeout(fetchStatus, 800);
    }
  } catch (_) {
    showToast(I18N.networkError || 'Erreur réseau', 'error');
    setTimeout(fetchStatus, 800);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveRotation(showFeedback) {
  const enabled = document.getElementById('rot-enabled')?.checked || false;
  const cycle   = document.getElementById('rot-cycle')?.checked   || false;
  const idle_timeout_minutes = Math.max(0, parseInt(document.getElementById('rot-idle-timeout')?.value, 10) || 0);
  try {
    const r = await fetch('/api/rotation', {
      method: 'POST',
      headers: _csrfHeaders(),
      body: JSON.stringify({ enabled, cycle, configs: _rotConfigs, idle_timeout_minutes }),
    });
    if (showFeedback) {
      if (r.ok) showToast(I18N.rotationSaved || 'Roulement enregistré', 'success');
      else showToast(I18N.error || 'Erreur', 'error');
    }
  } catch (_) {
    if (showFeedback) showToast(I18N.networkError || 'Erreur réseau', 'error');
  }
}

async function stopRotationCycle() {
  const btn = document.getElementById('btn-stop-cycle');
  if (btn) btn.disabled = true;
  _serverBtns().forEach(b => { if (b) b.disabled = true; });
  try {
    const r = await fetch('/api/server/stop', { method: 'POST', headers: _csrfHeaders() });
    const d = await r.json();
    if (d.ok) {
      showToast(I18N.cycleStopped || 'Cycle arrêté', 'success');
      [1000, 3000].forEach(ms => setTimeout(fetchStatus, ms));
    } else {
      showToast(d.error || I18N.error, 'error');
      setTimeout(fetchStatus, 800);
    }
  } catch (_) {
    showToast(I18N.networkError || 'Erreur réseau', 'error');
    setTimeout(fetchStatus, 800);
  } finally {
    if (btn) btn.disabled = false;
  }
}

if (document.getElementById('rot-enabled')) loadRotation();

// Boutons de confirmation générique (remplace les anciens onclick="return confirm(...)")
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-confirm]');
  if (!btn) return;
  e.preventDefault();
  if (await showConfirm(btn.dataset.confirm)) {
    const form = btn.closest('form');
    if (form) form.submit();
  }
});

// Page server.html — boutons (remplace les anciens onclick=)
document.getElementById('modal-create-submit-btn')?.addEventListener('click', submitCreate);
document.getElementById('modal-rename-submit-btn')?.addEventListener('click', submitRename);
document.getElementById('modal-config-error-close-btn')?.addEventListener('click', closeConfigErrorModal);
document.getElementById('modal-config-error-repair-btn')?.addEventListener('click', doRepairConfig);
document.getElementById('modal-logs-refresh-btn')?.addEventListener('click', loadLogs);
document.getElementById('srv-logs-open-btn')?.addEventListener('click', openLogs);
document.getElementById('srv-new-config-btn')?.addEventListener('click', () => openCreateModal(false));
document.getElementById('btn-start-cycle')?.addEventListener('click', startRotationCycle);
document.getElementById('btn-stop-cycle')?.addEventListener('click', stopRotationCycle);
document.getElementById('rot-add-btn')?.addEventListener('click', rotAddConfig);
document.getElementById('cars-select-all-btn')?.addEventListener('click', () => selectAllVisible(true));
document.getElementById('cars-deselect-all-btn')?.addEventListener('click', deselectAll);
document.getElementById('pi-sort-th')?.addEventListener('click', function () { togglePiSort(this); });
document.getElementById('save-all-btn')?.addEventListener('click', saveAll);
document.getElementById('srv-cat-filters')?.addEventListener('click', (e) => {
  const btn = e.target.closest('.cat-btn');
  if (btn) toggleCat(btn);
});
document.querySelector('.srv-config-grid')?.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action]');
  if (!btn) return;
  const name = btn.dataset.name;
  switch (btn.dataset.action) {
    case 'stop':      serverAction('stop'); break;
    case 'restart':   serverAction('restart'); break;
    case 'start':     startConfig(name); break;
    case 'edit':      editConfig(name, btn.dataset.editUrl); break;
    case 'rename':    serverSelectConfig(name); openRenameModal(); break;
    case 'duplicate': serverSelectConfig(name); openCreateModal(true); break;
    case 'delete':    serverSelectConfig(name); confirmDeleteConfig(); break;
  }
});

/* ── Petit modal flottant au survol (ex: alerte de collision d'ID de mod) ──
   Attribut data-hover-tip="texte" sur l'élément survolé. Apparaît au survol,
   disparaît dès que la souris quitte l'élément — pas l'infobulle native du
   navigateur (title=), un vrai petit modal positionné et stylé. */
let _hoverTipEl = null;

function _showHoverTip(target) {
  _hideHoverTip();
  const tip = document.createElement('div');
  tip.className = 'hover-tip';
  tip.textContent = target.dataset.hoverTip;
  document.body.appendChild(tip);
  const rect = target.getBoundingClientRect();
  const tipRect = tip.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - tipRect.width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
  let top = rect.bottom + 6;
  if (top + tipRect.height > window.innerHeight - 8) top = rect.top - tipRect.height - 6;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  _hoverTipEl = tip;
}

function _hideHoverTip() {
  if (_hoverTipEl) { _hoverTipEl.remove(); _hoverTipEl = null; }
}

document.addEventListener('pointerover', (e) => {
  const target = e.target.closest('[data-hover-tip]');
  if (target) _showHoverTip(target);
});
document.addEventListener('pointerout', (e) => {
  const target = e.target.closest('[data-hover-tip]');
  if (target && !target.contains(e.relatedTarget)) _hideHoverTip();
});
