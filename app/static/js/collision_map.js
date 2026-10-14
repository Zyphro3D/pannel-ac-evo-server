/* Carte des accrochages : plan du circuit + voiture 3D, reliés par le survol.
   Usage : initCollisionMap(rootElement) ; l'élément porte data-url (JSON de /accrochages/data/…) et un
   <script type="application/json" data-cm="i18n"> avec les textes traduits. Dépend de three.min.js (r128). */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const TYPES = [{ k: 0, key: 'wall', v: '--cm-wall' }, { k: 1, key: 'car', v: '--cm-car' }, { k: 2, key: 'object', v: '--cm-obj' }];

  window.initCollisionMap = function (root) {
    const q = n => root.querySelector('[data-cm="' + n + '"]');
    const I = JSON.parse(q('i18n').textContent);
    const css = n => getComputedStyle(root).getPropertyValue(n).trim();
    const fmt = n => n.toLocaleString(document.documentElement.lang || undefined);
    let rows = [], DATA = null, maxKmh = 1;
    const state = { types: new Set([0, 1, 2]), vmin: 0, dmg: false, sess: -1, drv: -1, hover: -1, pin: -1, heat: false };

    /* ── carte ── */
    const map = q('map'); let view = { x: 0, y: 0, w: 400, h: 400 };
    const gTrack = document.createElementNS(NS, 'g'), gDots = document.createElementNS(NS, 'g'); map.append(gTrack, gDots);
    const path = document.createElementNS(NS, 'path'); path.setAttribute('fill', 'none'); path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('stroke-linecap', 'round'); gTrack.append(path);
    let dotEls = [];
    const visible = r => state.types.has(r.type) && r.kmh >= state.vmin && (!state.dmg || r.dmg) && (state.sess < 0 || r.sess === state.sess) && (state.drv < 0 || r.drv === state.drv || r.with.includes(state.drv));

    function styleMap() {
      path.setAttribute('stroke', css('--cm-track')); path.setAttribute('stroke-width', 5); path.setAttribute('stroke-opacity', '.6');
      rows.forEach(r => {
        const c = dotEls[r.i], on = visible(r), hot = (r.i === state.hover || r.i === state.pin);
        c.style.display = on ? '' : 'none'; if (!on) return;
        const base = 1.4 + Math.sqrt(r.kmh / maxKmh) * 2.4;
        c.setAttribute('fill', css(TYPES[r.type].v));
        if (state.heat) { c.setAttribute('r', (hot ? 6 : 7 + base * 2).toFixed(1)); c.setAttribute('fill-opacity', hot ? 1 : .07); c.setAttribute('stroke', 'none'); }
        else { c.setAttribute('r', (hot ? base + 3.2 : base).toFixed(1)); c.setAttribute('fill-opacity', hot ? 1 : .62); c.setAttribute('stroke', hot ? css('--cm-fg') : 'none'); c.setAttribute('stroke-width', hot ? 1.2 : 0); }
      });
    }
    const setView = () => map.setAttribute('viewBox', view.x + ' ' + view.y + ' ' + view.w + ' ' + view.h);
    let drag = null;
    map.addEventListener('wheel', e => {
      e.preventDefault(); const p = map.getBoundingClientRect(), k = Math.exp(e.deltaY * .0015);
      const nx = view.x + ((e.clientX - p.left) / p.width) * view.w, ny = view.y + ((e.clientY - p.top) / p.height) * view.h;
      const nw = Math.min(400, Math.max(40, view.w * k)); view.x = nx - ((e.clientX - p.left) / p.width) * nw; view.y = ny - ((e.clientY - p.top) / p.height) * nw; view.w = view.h = nw; setView();
    }, { passive: false });
    map.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; map.setPointerCapture(e.pointerId); });
    map.addEventListener('pointermove', e => { if (!drag) return; const p = map.getBoundingClientRect(); view.x = drag.vx - ((e.clientX - drag.x) / p.width) * view.w; view.y = drag.vy - ((e.clientY - drag.y) / p.height) * view.h; setView(); });
    map.addEventListener('pointerup', () => drag = null); map.addEventListener('click', () => pin(-1));
    q('reset').addEventListener('click', () => { view = { x: 0, y: 0, w: 400, h: 400 }; setView(); });
    const setHeat = on => { state.heat = on; q('pts').setAttribute('aria-pressed', !on); q('heat').setAttribute('aria-pressed', on); styleMap(); };
    q('pts').addEventListener('click', () => setHeat(false)); q('heat').addEventListener('click', () => setHeat(true));

    /* ── voiture 3D ── */
    const canvas = q('scene');
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(36, 1, .1, 100);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445066, .95)); const dl = new THREE.DirectionalLight(0xffffff, .6); dl.position.set(3, 6, 4); scene.add(dl);
    const carGroup = new THREE.Group(); scene.add(carGroup);
    const carMat = new THREE.MeshStandardMaterial({ color: 0x222c3d, roughness: .7, metalness: .1, transparent: true, opacity: .62, depthWrite: false });
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x6f819f, transparent: true, opacity: .9 });
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x2a2f3a, roughness: .9, transparent: true, opacity: .8, depthWrite: false });
    const addEdges = (mesh, thr) => { const e = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, thr), edgeMat); e.position.copy(mesh.position); e.rotation.copy(mesh.rotation); carGroup.add(e); };
    (function buildCar() {
      const P = [[-2.50, -0.26], [-2.56, 0.06], [-2.40, 0.30], [-1.65, 0.42], [-1.15, 0.78], [-0.55, 0.90], [0.15, 0.88], [0.85, 0.50], [1.75, 0.30], [2.40, 0.10], [2.52, -0.06], [2.56, -0.27]];
      const sh = new THREE.Shape(); P.forEach((p, i) => i ? sh.lineTo(p[0], p[1]) : sh.moveTo(p[0], p[1])); sh.closePath();
      const g = new THREE.ExtrudeGeometry(sh, { depth: 1.9, bevelEnabled: true, bevelThickness: .08, bevelSize: .08, bevelSegments: 3 });
      g.rotateY(-Math.PI / 2); g.translate(.95, 0, 0);
      const body = new THREE.Mesh(g, carMat); carGroup.add(body); addEdges(body, 28);
      [[.95, 1.42], [-.95, 1.42], [.95, -1.38], [-.95, -1.38]].forEach(([x, z]) => { const w = new THREE.Mesh(new THREE.CylinderGeometry(.34, .34, .32, 28), wheelMat); w.rotation.z = Math.PI / 2; w.position.set(x, -.01, z); carGroup.add(w); addEdges(w, 28); });
      const wing = new THREE.Mesh(new THREE.BoxGeometry(2.0, .05, .42), carMat); wing.position.set(0, .86, -2.38); carGroup.add(wing); addEdges(wing, 28);
      [-1, 1].forEach(s => { const pl = new THREE.Mesh(new THREE.BoxGeometry(.04, .34, .5), carMat); pl.position.set(s * 1.0, .78, -2.38); carGroup.add(pl); });
      const spl = new THREE.Mesh(new THREE.BoxGeometry(2.0, .04, .38), carMat); spl.position.set(0, -.29, 2.55); carGroup.add(spl); addEdges(spl, 28);
      const grid = new THREE.GridHelper(8, 16, 0x666666, 0x666666); grid.position.y = -.35; grid.material.transparent = true; grid.material.opacity = .3; scene.add(grid);
      const nose = new THREE.Mesh(new THREE.ConeGeometry(.1, .3, 12), new THREE.MeshBasicMaterial({ color: 0xff6a45 })); nose.rotation.x = Math.PI / 2; nose.position.set(0, -.33, 3.15); scene.add(nose);
    })();
    let inst = null, idToRow = [];
    const halo = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: .28, depthTest: false })); halo.visible = false; halo.renderOrder = 10; scene.add(halo);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1, .09, 8, 28), new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false })); ring.visible = false; ring.renderOrder = 11; scene.add(ring);
    const tmpM = new THREE.Matrix4(), qt = new THREE.Quaternion(), Sv = new THREE.Vector3(), Pv = new THREE.Vector3();
    const radius = r => .03 + Math.sqrt(r.kmh / maxKmh) * .07;
    function updateMarkers() {
      if (inst) { scene.remove(inst); inst.dispose(); }
      inst = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 14, 10), new THREE.MeshStandardMaterial({ roughness: .4, transparent: true, opacity: .92 }), Math.max(1, rows.length));
      scene.add(inst); idToRow = []; let n = 0; const cols = TYPES.map(t => new THREE.Color(css(t.v)));
      rows.forEach(r => { if (!visible(r)) return; const s = radius(r); Pv.set(r.rx, r.ry, r.rz); Sv.set(s, s, s); tmpM.compose(Pv, qt, Sv); inst.setMatrixAt(n, tmpM); inst.setColorAt(n, cols[r.type]); idToRow[n] = r.i; n++; });
      inst.count = n; inst.instanceMatrix.needsUpdate = true; if (inst.instanceColor) inst.instanceColor.needsUpdate = true; placeHighlight();
    }
    function placeHighlight() {
      const id = state.hover >= 0 ? state.hover : state.pin;
      if (id < 0 || !visible(rows[id])) { halo.visible = false; ring.visible = false; return; }
      const r = rows[id], s = radius(r); halo.position.set(r.rx, r.ry, r.rz); halo.scale.setScalar(s * 2.6); halo.visible = true; ring.position.copy(halo.position); ring.scale.setScalar(s * 1.7); ring.visible = true;
    }
    const cam = { az: .9, el: .34, dist: 10.5, tx: 0, ty: .55, tz: 0, auto: false };
    const VIEWS = { iso: [.9, .34, 10.5], top: [0, 1.5, 10.5], front: [Math.PI, .1, 10], rear: [0, .1, 10], left: [-Math.PI / 2, .1, 10], right: [Math.PI / 2, .1, 10] };
    let tween = null;
    const applyCam = () => { const c = Math.cos(cam.el), s = Math.sin(cam.el); camera.position.set(cam.tx + cam.dist * c * Math.sin(cam.az), cam.ty + cam.dist * s, cam.tz + cam.dist * c * Math.cos(cam.az)); camera.lookAt(cam.tx, cam.ty, cam.tz); };
    const viewBtns = root.querySelectorAll('[data-cm-view]');
    viewBtns.forEach(b => b.addEventListener('click', () => { viewBtns.forEach(x => x.setAttribute('aria-pressed', x === b)); const v = VIEWS[b.dataset.cmView]; tween = { from: { az: cam.az, el: cam.el, dist: cam.dist }, to: { az: v[0], el: v[1], dist: v[2] }, t: 0 }; cam.auto = false; q('spin').setAttribute('aria-pressed', 'false'); }));
    q('spin').addEventListener('click', () => { cam.auto = !cam.auto; q('spin').setAttribute('aria-pressed', cam.auto); });
    let d3 = null;
    canvas.addEventListener('pointerdown', e => { d3 = { x: e.clientX, y: e.clientY, az: cam.az, el: cam.el, moved: 0 }; canvas.setPointerCapture(e.pointerId); tween = null; });
    canvas.addEventListener('pointermove', e => { if (d3 && e.buttons) { const dx = e.clientX - d3.x, dy = e.clientY - d3.y; d3.moved = Math.max(d3.moved, Math.abs(dx) + Math.abs(dy)); cam.az = d3.az - dx * .008; cam.el = Math.max(-.1, Math.min(1.5, d3.el + dy * .006)); } else pick(e); });
    canvas.addEventListener('pointerup', e => { if (d3 && d3.moved < 5) pick(e, true); d3 = null; });
    canvas.addEventListener('pointerleave', () => { if (!d3) hover(-1); });
    canvas.addEventListener('wheel', e => { e.preventDefault(); cam.dist = Math.max(4, Math.min(16, cam.dist * Math.exp(e.deltaY * .001))); }, { passive: false });
    const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
    function pick(e, click) { if (!inst) return; const p = canvas.getBoundingClientRect(); mouse.set(((e.clientX - p.left) / p.width) * 2 - 1, -((e.clientY - p.top) / p.height) * 2 + 1); ray.setFromCamera(mouse, camera); const hit = ray.intersectObject(inst)[0]; const id = hit ? idToRow[hit.instanceId] : -1; if (click) pin(id); else hover(id); }
    function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; if (!w || !h) return; if (canvas.width !== Math.round(w * renderer.getPixelRatio())) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); } }
    let last = 0, running = true;
    function loop(t) {
      if (!running) return; requestAnimationFrame(loop);
      if (!document.body.contains(root)) { running = false; return; }
      const dt = Math.min(.05, (t - last) / 1000 || 0); last = t; resize();
      if (tween) { tween.t = Math.min(1, tween.t + dt * 2.4); const k = 1 - Math.pow(1 - tween.t, 3); let da = tween.to.az - tween.from.az; da = Math.atan2(Math.sin(da), Math.cos(da)); cam.az = tween.from.az + da * k; cam.el = tween.from.el + (tween.to.el - tween.from.el) * k; cam.dist = tween.from.dist + (tween.to.dist - tween.from.dist) * k; if (tween.t >= 1) tween = null; }
      if (cam.auto && !d3) cam.az += dt * .5; applyCam();
      const hid = state.hover >= 0 ? state.hover : state.pin; if (halo.visible && hid >= 0) halo.scale.setScalar(radius(rows[hid]) * 2.6 * (1 + .08 * Math.sin(t / 220)));
      renderer.render(scene, camera);
    }

    /* ── fiche, filtres, synchronisation ── */
    const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    function where(r) { const fb = r.rz > .8 ? I.front : r.rz < -.8 ? I.rear : '', lr = r.rx > .3 ? I.right : r.rx < -.3 ? I.left : ''; return (fb + ' ' + lr).trim() || I.center; }
    function info() {
      const id = state.hover >= 0 ? state.hover : state.pin, el = q('info');
      if (id < 0) { const v = rows.filter(visible), top = v.slice().sort((a, b) => b.kmh - a.kmh)[0];
        el.innerHTML = '<h3>' + esc(I.hover_hint_title) + '</h3><div class="kv wide"><span>' + esc(I.tip) + '</span><b class="plain">' + esc(I.hover_hint) + '</b></div>' + (top ? '<div class="kv"><span>' + esc(I.top_hit) + '</span><b>' + top.kmh.toFixed(0) + ' km/h</b></div><div class="kv"><span>' + esc(I.type) + '</span><b>' + esc(I.types[top.key]) + '</b></div>' : ''); return; }
      const r = rows[id], who = DATA.drivers[r.drv], others = r.with.map(d => DATA.drivers[d]).filter(Boolean);
      el.innerHTML = '<h3>' + esc(state.hover < 0 ? I.pinned : I.hovered) + '</h3>' +
        '<div class="kv"><span>' + esc(I.type) + '</span><b style="color:var(' + TYPES[r.type].v + ')">' + esc(I.types[r.key]) + '</b></div>' +
        '<div class="kv"><span>' + esc(I.speed) + '</span><b>' + r.kmh.toFixed(1) + ' km/h</b><div class="gauge"><div style="width:' + Math.min(100, r.kmh / maxKmh * 100) + '%"></div></div></div>' +
        '<div class="kv"><span>' + esc(I.damage) + '</span><b>' + esc(r.dmg ? I.yes : I.no) + '</b></div>' +
        '<div class="kv"><span>' + esc(I.on_car) + '</span><b>' + esc(where(r)) + '</b></div>' +
        '<div class="kv"><span>' + esc(I.driver) + '</span><b class="plain">' + esc(who) + (others.length ? ' <span class="dimmed">' + esc(I.with) + ' ' + esc(others.join(', ')) + '</span>' : '') + '</b></div>' +
        '<div class="kv"><span>' + esc(I.session) + '</span><b class="plain">' + esc(DATA.sessions[r.sess].label) + '</b></div>';
    }
    function hover(i) { if (state.hover === i) return; state.hover = i; styleMap(); placeHighlight(); info(); canvas.style.cursor = i >= 0 ? 'pointer' : 'grab'; }
    function pin(i) { state.pin = (state.pin === i ? -1 : i); styleMap(); placeHighlight(); info(); }
    function refresh() {
      const v = rows.filter(visible); q('s-count').textContent = fmt(v.length);
      q('s-avg').textContent = v.length ? (v.reduce((a, r) => a + r.kmh, 0) / v.length).toFixed(0) : '—';
      q('s-max').textContent = v.length ? Math.max.apply(null, v.map(r => r.kmh)).toFixed(0) : '—';
      styleMap(); updateMarkers(); info();
    }
    function buildFilters() {
      const cnt = { 0: 0, 1: 0, 2: 0 }; rows.forEach(r => cnt[r.type]++);
      q('types').innerHTML = TYPES.map(t => '<button type="button" class="cm-chip" data-k="' + t.k + '" aria-pressed="true"><i style="background:var(' + t.v + ')"></i>' + esc(I.types[t.key]) + ' <span class="cm-n">' + fmt(cnt[t.k]) + '</span></button>').join('');
      q('types').querySelectorAll('.cm-chip').forEach(b => b.addEventListener('click', () => { const k = +b.dataset.k; state.types.has(k) ? state.types.delete(k) : state.types.add(k); b.setAttribute('aria-pressed', state.types.has(k)); refresh(); }));
      const ss = q('sess'); ss.innerHTML = '<option value="-1">' + esc(I.all) + '</option>' + DATA.sessions.map((s, i) => '<option value="' + i + '">' + esc(s.label) + '</option>').join('');
      ss.closest('label').hidden = DATA.sessions.length < 2;
      const per = {}; rows.forEach(r => per[r.drv] = (per[r.drv] || 0) + 1);
      const order = Object.keys(per).map(Number).sort((a, b) => per[b] - per[a]);
      q('drv').innerHTML = '<option value="-1">' + esc(I.all) + '</option>' + order.map(d => '<option value="' + d + '">' + esc(DATA.drivers[d]) + ' (' + per[d] + ')</option>').join('');
      const vm = q('vmin'); vm.max = Math.ceil(maxKmh / 5) * 5; vm.value = 0; q('vmin-o').textContent = '0 km/h';
      vm.addEventListener('input', e => { state.vmin = +e.target.value; q('vmin-o').textContent = state.vmin + ' km/h'; refresh(); });
      q('dmg').addEventListener('change', e => { state.dmg = e.target.checked; refresh(); });
      ss.addEventListener('change', e => { state.sess = +e.target.value; refresh(); });
      q('drv').addEventListener('change', e => { state.drv = +e.target.value; refresh(); });
    }
    function load(data) {
      DATA = data; path.setAttribute('d', data.path);
      rows = data.rows.map((r, i) => ({ i, mx: r[0], my: r[1], rx: r[2], ry: r[3], rz: r[4], kmh: r[5], type: r[6], key: TYPES[r[6]].key, dmg: !!r[7], sess: r[8], drv: r[9], with: r[10] || [] }));
      maxKmh = Math.max(1, ...rows.map(r => r.kmh));
      dotEls = []; gDots.innerHTML = '';
      rows.slice().sort((a, b) => a.kmh - b.kmh).forEach(r => {
        const c = document.createElementNS(NS, 'circle'); c.setAttribute('cx', r.mx); c.setAttribute('cy', r.my); c.classList.add('dot');
        c.addEventListener('pointerenter', () => hover(r.i)); c.addEventListener('pointerleave', () => hover(-1)); c.addEventListener('click', e => { e.stopPropagation(); pin(r.i); });
        gDots.append(c); dotEls[r.i] = c;
      });
      buildFilters(); halo.material.color.set(css('--cm-fg')); ring.material.color.set(css('--cm-fg')); refresh();
      q('empty').hidden = rows.length > 0;
    }
    fetch(root.dataset.url, { credentials: 'same-origin' }).then(r => r.json()).then(d => { load(d); requestAnimationFrame(loop); }).catch(() => { q('empty').hidden = false; });
  };
})();
