/* Recherche « Où régler… ? » du menu Admin (Ctrl+K). L'index vient d'app/services/admin_nav.py,
   rendu dans la page (#admin-find-data) : rien n'est demandé au serveur pendant la frappe. */
(function () {
  const box = document.getElementById('admin-find');
  const data = document.getElementById('admin-find-data');
  if (!box || !data) return;
  const index = JSON.parse(data.textContent || '[]');
  const input = document.getElementById('admin-find-input');
  const list = document.getElementById('admin-find-res');
  const norm = s => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const rows = index.map(r => ({ r, label: norm(r.label), hay: norm([r.label, r.group, r.path, r.keywords].join(' ')) }));
  let shown = [], sel = 0;

  function render() {
    const words = norm(input.value).split(/\s+/).filter(Boolean);
    shown = rows.map(x => {
      let score = 0;
      for (const w of words) {
        if (!x.hay.includes(w)) return null;
        score += x.label.includes(w) ? 2 : 1;
      }
      return [score, x.r];
    }).filter(Boolean).sort((a, b) => b[0] - a[0]).slice(0, 9).map(a => a[1]);
    if (!words.length) shown = index.slice(0, 7);
    list.textContent = '';
    shown.forEach((r, i) => list.appendChild(item(r.icon, r.label, r.group, r.path, r.url, i)));
    if (!shown.length) {
      const li = document.createElement('li');
      li.className = 'admin-find-empty';
      li.textContent = box.dataset.empty.replace('__Q__', input.value);
      list.appendChild(li);
    }
    if (words.length) {        // dernier résultat : la documentation publique
      const docUrl = box.dataset.docUrl;
      list.appendChild(item('📖', box.dataset.doc, '', docUrl.replace(/^https:\/\//, ''), docUrl, shown.length, true));
      shown = shown.concat([{ url: docUrl, external: true }]);
    }
    sel = 0;
    mark();
  }

  // Construit une ligne avec textContent : les libellés traduits ne passent jamais par innerHTML.
  function item(icon, label, group, path, url, i, external) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = url;
    a.dataset.i = i;
    a.setAttribute('role', 'option');
    if (external) { a.target = '_blank'; a.rel = 'noopener'; }
    const ic = document.createElement('span'); ic.className = 'admin-item-ic'; ic.textContent = icon;
    const tx = document.createElement('span'); tx.className = 'admin-find-tx'; tx.textContent = label;
    const p = document.createElement('small');
    if (group) { const b = document.createElement('b'); b.textContent = group; p.appendChild(b); p.append(' › '); }
    p.append(path);
    tx.appendChild(p);
    a.append(ic, tx);
    li.appendChild(a);
    return li;
  }

  function mark() {
    list.querySelectorAll('a').forEach(a => {
      const on = Number(a.dataset.i) === sel;
      a.classList.toggle('sel', on);
      a.setAttribute('aria-selected', String(on));
      if (on) a.scrollIntoView({ block: 'nearest' });
    });
  }

  function open() {
    box.hidden = false;
    document.documentElement.classList.add('admin-find-open');
    input.value = '';
    render();
    input.focus();
  }
  function close() {
    box.hidden = true;
    document.documentElement.classList.remove('admin-find-open');
  }
  function go(i) {
    const r = shown[i];
    if (!r) return;
    if (r.external) { window.open(r.url, '_blank', 'noopener'); return; }
    close();
    // Même page, autre ancre : le navigateur ne recharge pas, on fait défiler nous-mêmes.
    const target = new URL(r.url, location.href);
    if (target.pathname + target.search === location.pathname + location.search && target.hash) {
      location.hash = target.hash;
      document.querySelector(target.hash)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      location.href = r.url;
    }
  }

  input.addEventListener('input', render);
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, shown.length - 1); mark(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); mark(); e.preventDefault(); }
    else if (e.key === 'Enter') { go(sel); e.preventDefault(); }
  });
  list.addEventListener('click', e => {
    const a = e.target.closest('a');
    if (!a) return;
    e.preventDefault();
    go(Number(a.dataset.i));
  });
  box.addEventListener('click', e => { if (e.target === box) close(); });
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); box.hidden ? open() : close(); }
    else if (e.key === 'Escape' && !box.hidden) close();
  });
  document.querySelectorAll('[data-admin-find]').forEach(b => b.addEventListener('click', open));
})();
