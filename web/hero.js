// Plunge home page hero: a flat game screenshot wraps around you and becomes a VR view.
// Scrolling drives the animation (it also creeps forward on its own), and the page stays put until it finishes.
// Screenshots are from free, open-source games (see /credits). If anything here fails, the page unlocks and keeps working.
let THREE;
const frame = document.querySelector("[data-hero-frame]");
const canvas = frame && frame.querySelector("canvas");
const root = document.documentElement;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const IMAGES = ["veloren-sunset", "xonotic", "supertuxkart", "0ad", "minetest"];

// ---- scroll lock: the page can't scroll until the animation is done -----------------------------------------------------
let P = 0;            // target progress, 0..1
let locked = false;
const lockKeys = new Set([" ", "PageDown", "PageUp", "ArrowDown", "ArrowUp", "End", "Home"]);
let lastInput = 0;
const nudge = (d) => { P = Math.min(1, Math.max(0, P + d)); lastInput = performance.now(); };
const onWheel = (e) => { e.preventDefault(); nudge((e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY) * 0.00055); };
let ty = 0;
const onTouchStart = (e) => { ty = e.touches[0].clientY; };
const onTouchMove = (e) => { e.preventDefault(); const y = e.touches[0].clientY; nudge((ty - y) * 0.0024); ty = y; };
const onKey = (e) => {
  if (!lockKeys.has(e.key) || /^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(document.activeElement && document.activeElement.tagName)) return;
  e.preventDefault();
  nudge((e.key === "ArrowUp" || e.key === "PageUp" || e.key === "Home" ? -1 : 1) * (e.key.startsWith("Arrow") ? 0.04 : 0.12));
};
function lock() {
  if (locked) return;
  locked = true;
  root.classList.add("locked");
  addEventListener("wheel", onWheel, { passive: false });
  addEventListener("touchstart", onTouchStart, { passive: true });
  addEventListener("touchmove", onTouchMove, { passive: false });
  addEventListener("keydown", onKey);
}
function unlock() {
  if (!locked) return;
  locked = false;
  root.classList.remove("locked");
  removeEventListener("wheel", onWheel);
  removeEventListener("touchstart", onTouchStart);
  removeEventListener("touchmove", onTouchMove);
  removeEventListener("keydown", onKey);
  if (frame) frame.dataset.done = "true";
  document.dispatchEvent(new Event("plunge:unlocked"));
}

// ---- replay: scrolling up from the very top locks the page again and plays the animation backwards ---------------------------
// A fresh gesture is needed (a pause since the last wheel event, and a moment spent at the top), so momentum from scrolling
// back up the page can't rewind it by accident.
let atTopSince = scrollY <= 2 ? performance.now() : 0, lastWheel = 0, replayTouchY = null;
const canReplay = () => !locked && frame && frame.classList.contains("ready") && !frame.classList.contains("nogl") && !reduced
  && scrollY <= 2 && atTopSince && performance.now() - atTopSince > 350;
function replay(d) {
  P = Math.min(P, 0.999);          // start from the end state, then walk back
  lock();
  if (frame) frame.dataset.done = "false";
  nudge(d);
}
addEventListener("scroll", () => { if (scrollY <= 2) { if (!atTopSince) atTopSince = performance.now(); } else atTopSince = 0; }, { passive: true });
addEventListener("wheel", (e) => {
  const now = performance.now(), gap = now - lastWheel;
  lastWheel = now;
  if (e.deltaY < -4 && gap > 140 && canReplay()) replay((e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY) * 0.00055);
}, { passive: true });
addEventListener("touchstart", (e) => { replayTouchY = canReplay() ? e.touches[0].clientY : null; }, { passive: true });
addEventListener("touchmove", (e) => {
  if (replayTouchY === null || locked) return;
  const dy = e.touches[0].clientY - replayTouchY;          // finger moving down = scrolling up
  if (dy > 14) { replayTouchY = null; ty = e.touches[0].clientY; replay(-0.02); }
}, { passive: true });
addEventListener("keydown", (e) => {
  if ((e.key === "ArrowUp" || e.key === "PageUp" || e.key === "Home") && canReplay() && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName)) replay(-0.04);
});
const skip = frame && frame.querySelector("[data-skip]");
if (skip) skip.addEventListener("click", () => { P = 1; });

const preset = parseFloat(new URLSearchParams(location.search).get("p"));   // ?p=0.5 shows that moment of the animation, unlocked (for previews)
if (frame && canvas) {
  if (!Number.isNaN(preset)) P = Math.min(1, Math.max(0, preset));
  else if (!reduced && scrollY < 40) lock();      // someone who reloaded halfway down the page is not locked in
  setTimeout(() => { if (locked && !frame.classList.contains("ready")) unlock(); }, 8000);   // never trap anyone if the 3D never starts
  import("/vendor/three.module.min.js").then((m) => { THREE = m; start(); }).catch(() => { frame.classList.add("nogl"); unlock(); });
}

function start() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  } catch (e) {
    frame.classList.add("nogl");
    unlock();
    return;
  }
  renderer.setClearColor(0x030305);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();

  // ---- the ring of screens: six screenshots laid in a row (flat), which bend into a circle around the camera -----------------
  const N = IMAGES.length, R = 6;
  const STEP = (Math.PI * 2) / N, GAP = 0.06;
  const Wp = R * (STEP - GAP), Hp = (Wp * 9) / 16;
  const arcStep = R * STEP;
  const loader = new THREE.TextureLoader();
  const panels = [];
  for (let i = 0; i < N; i++) {
    const g = new THREE.PlaneGeometry(Wp, Hp, 40, 1);
    const base = Float32Array.from(g.attributes.position.array);
    const mat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, side: THREE.DoubleSide, toneMapped: false });
    const mesh = new THREE.Mesh(g, mat);
    mesh.frustumCulled = false;
    loader.load("/img/" + IMAGES[i] + ".jpg", (tx) => {
      tx.colorSpace = THREE.SRGBColorSpace;
      tx.anisotropy = 4;
      const a = tx.image.width / tx.image.height, want = 16 / 9;     // crop to 16:9 so every screen is the same shape
      if (a > want) { tx.repeat.x = want / a; tx.offset.x = (1 - tx.repeat.x) / 2; } else { tx.repeat.y = a / want; tx.offset.y = (1 - tx.repeat.y) / 2; }
      mat.map = tx; mat.color.set(0xffffff); mat.needsUpdate = true;
    });
    scene.add(mesh);
    panels.push({ mesh, base, mat, i });
  }
  function bend(k) {                       // k: 0 = flat strip, 1 = full ring
    const kap = k / R;
    for (const p of panels) {
      const pos = p.mesh.geometry.attributes.position;
      for (let v = 0; v < pos.count; v++) {
        const s = p.base[v * 3], y = p.base[v * 3 + 1];
        const u = p.i * arcStep + s;
        if (kap < 1e-4) { pos.setXYZ(v, u, y, -R); }
        else { pos.setXYZ(v, Math.sin(kap * u) / kap, y, -R + (1 - Math.cos(kap * u)) / kap); }
      }
      pos.needsUpdate = true;
      p.mat.opacity = p.i === 0 ? 1 : Math.min(1, Math.max(0, (k - 0.08) / 0.4));
    }
  }

  // a faint grid floor and some stars, so the ring feels like a room
  const grid = new THREE.GridHelper(60, 60, 0x1f6bff, 0x10192e);
  grid.position.y = -Hp / 2 - 0.6;
  grid.material.transparent = true;
  grid.material.opacity = 0;
  scene.add(grid);
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const sp = new Float32Array(420 * 3);
  for (let i = 0; i < 420; i++) { const a = rnd() * 6.283, b = rnd() * 3.1416, r = 40; sp.set([r * Math.sin(b) * Math.cos(a), r * Math.cos(b), r * Math.sin(b) * Math.sin(a)], i * 3); }
  const sg = new THREE.BufferGeometry();
  sg.setAttribute("position", new THREE.BufferAttribute(sp, 3));
  const stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 1.4, sizeAttenuation: false, transparent: true, opacity: 0 }));
  scene.add(stars);

  // ---- camera path, driven by progress ------------------------------------------------------------------------------------------
  const camera = new THREE.PerspectiveCamera(22, 16 / 9, 0.1, 200);
  const A = 0.30, B = 0.62, STEREO = 0.74;
  const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const clamp01 = (x) => Math.min(1, Math.max(0, x));
  const FOV0 = 22, FOV1 = 80;
  // at the start the first screenshot covers the whole frame (no black bars), whatever shape the frame is
  const startZ = (aspect) => Math.min(Hp, Wp / aspect) / (2 * Math.tan((FOV0 * Math.PI) / 360)) - R;
  let label = "", idle = 0;
  const labelEl = frame.querySelector("[data-phase-label]");

  function pose(p) {
    const kz = ease(clamp01((p - A) / (B - A)));
    const bend01 = kz;
    const fov = FOV0 + (FOV1 - FOV0) * kz;
    const z = startZ(w / Math.max(1, h)) * (1 - kz);
    const ryaw = p > B ? -((p - B) / (1 - B)) * Math.PI * 1.9 : 0;                 // look around the ring
    const sway = p > B ? Math.sin(idle * 0.7) * 0.03 + Math.sin(idle * 0.31) * 0.02 : 0;
    camera.fov = fov;
    camera.position.set(0, 0, z + (p < A ? Math.sin(p / A * 3) * 0.05 : 0));
    camera.rotation.set(sway * 0.5, ryaw + (p >= 0.999 ? Math.sin(idle * 0.25) * 0.15 : 0), sway * 0.4, "YXZ");
    camera.updateProjectionMatrix();
    bend(bend01);
    grid.material.opacity = 0.5 * clamp01((kz - 0.4) / 0.6);
    stars.material.opacity = 0.7 * clamp01((kz - 0.3) / 0.7);
    const next = kz > 0.5 ? "VR" : "Flat";
    if (next !== label) { label = next; frame.dataset.phase = next === "VR" ? "vr" : "flat"; if (labelEl) labelEl.textContent = next; }
  }

  let w = 0, h = 0;
  function resize() {
    const r = frame.getBoundingClientRect();
    w = Math.max(2, Math.round(r.width)); h = Math.max(2, Math.round(r.height));
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
    renderer.setSize(w, h, false);
  }
  new ResizeObserver(resize).observe(frame);
  resize();

  const eye = new THREE.Vector3();
  function draw(p) {
    pose(p);
    const stereo = p >= STEREO;
    frame.classList.toggle("stereo", stereo);
    renderer.setScissorTest(stereo);
    if (!stereo) {
      renderer.setViewport(0, 0, w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
      return;
    }
    camera.aspect = (w / 2) / h;
    camera.updateProjectionMatrix();
    const base = camera.position.clone();
    for (const side of [-1, 1]) {
      eye.set(side * 0.12, 0, 0).applyQuaternion(camera.quaternion);
      camera.position.copy(base).add(eye);
      const vx = side < 0 ? 0 : Math.floor(w / 2);
      renderer.setViewport(vx, 0, Math.floor(w / 2), h);
      renderer.setScissor(vx, 0, Math.floor(w / 2), h);
      renderer.render(scene, camera);
    }
    camera.position.copy(base);
  }

  // ---- loop ------------------------------------------------------------------------------------------------------------------------
  let shown = reduced ? 0.7 : 0, last = performance.now(), visible = true;
  if (reduced && Number.isNaN(preset)) P = 0.7;
  if (!Number.isNaN(preset)) shown = P;
  new IntersectionObserver((e) => { visible = e[0].isIntersecting; }, { threshold: 0.02 }).observe(frame);
  const hint = frame.querySelector("[data-hint]");

  function tick(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    idle += dt;
    if (locked && !document.hidden && now - lastInput > 2500) P = Math.min(1, P + dt * 0.012);   // creeps on its own; scrolling makes it go faster
    shown += (P - shown) * Math.min(1, dt * 7);                                // smooth
    if (Math.abs(P - shown) < 0.0004) shown = P;
    if (hint) hint.style.opacity = locked ? String(1 - clamp01(shown * 10)) : "0";
    if (locked && shown >= 0.999 && P >= 1) unlock();
    if (visible && !document.hidden) draw(shown);
    requestAnimationFrame(tick);
  }
  draw(shown);
  frame.classList.add("ready");
  requestAnimationFrame(tick);
}
