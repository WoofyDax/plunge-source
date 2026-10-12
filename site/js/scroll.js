// Scroll effects for the Plunge home page. Everything degrades to plain, fully visible content if this file never runs.
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const easeOut = (x) => 1 - Math.pow(1 - x, 3);
const root = document.documentElement;
root.classList.add("js");

if (reduced) {
  $$("[data-reveal]").forEach((e) => e.classList.add("in"));
  $$("[data-live]").forEach((e) => e.classList.add("live"));
  $$("[data-words] span").forEach((s) => (s.style.opacity = "1"));
} else {
  // ---- reveal on enter, and start the little animated mock-ups only while they are on screen ------------------------------------
  const rev = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); rev.unobserve(e.target); } }), { threshold: 0.18, rootMargin: "0px 0px -6% 0px" });
  $$("[data-reveal]").forEach((e, i) => { e.style.setProperty("--d", ((i % 4) * 70) + "ms"); rev.observe(e); });
  const live = new IntersectionObserver((es) => es.forEach((e) => e.target.classList.toggle("live", e.isIntersecting)), { threshold: 0.3 });
  $$("[data-live]").forEach((e) => live.observe(e));

  // ---- word-by-word reveal of the big intro sentence ----------------------------------------------------------------------------
  const wordBox = document.querySelector("[data-words]");
  let words = [];
  if (wordBox) {
    const nodes = Array.from(wordBox.childNodes);
    wordBox.textContent = "";
    for (const n of nodes) {
      const em = n.nodeType === 1 ? n.tagName === "EM" : false;
      const parts = (n.textContent || "").split(/(\s+)/);
      for (const part of parts) {
        if (!part) continue;
        if (/^\s+$/.test(part)) { wordBox.append(" "); continue; }
        const s = document.createElement("span");
        s.textContent = part;
        if (em) s.className = "em";
        wordBox.append(s);
        words.push(s);
      }
    }
  }

  const bar = document.querySelector("[data-progress]");
  const nav = document.querySelector(".nav");
  const vises = $$(".vis"), gal = document.querySelector("[data-gallery]"), track = gal && gal.querySelector("[data-track]");
  const cards = $$("[data-card]"), fin = document.querySelector("[data-final]");
  let lastY = scrollY, ticking = false;

  function update() {
    ticking = false;
    const vh = innerHeight, y = scrollY;
    if (bar) bar.style.transform = "scaleX(" + clamp01(y / Math.max(1, root.scrollHeight - vh)) + ")";
    if (nav) { if (y > lastY + 6 && y > 160) nav.classList.add("hide"); else if (y < lastY - 6 || y < 60) nav.classList.remove("hide"); }
    lastY = y;

    if (wordBox && words.length) {
      const r = wordBox.getBoundingClientRect();
      const p = clamp01((vh * 0.82 - r.top) / (vh * 0.5));
      words.forEach((s, i) => { s.style.opacity = String(0.18 + 0.82 * clamp01(p * (words.length + 3) - i)); });
    }
    for (const v of vises) {
      const r = v.getBoundingClientRect();
      const enter = clamp01((vh * 0.98 - r.top) / (vh * 0.55));
      const e = easeOut(enter), mid = (r.top + r.height / 2 - vh / 2) / vh;
      v.style.transform = "perspective(1100px) rotateX(" + ((1 - e) * 9).toFixed(2) + "deg) translateY(" + ((1 - e) * 40 + mid * -22).toFixed(1) + "px) scale(" + (0.9 + 0.1 * e).toFixed(3) + ")";
      v.style.opacity = String(0.25 + 0.75 * e);
    }
    if (gal && track) {
      const r = gal.getBoundingClientRect();
      const p = clamp01((vh - r.top) / (r.height + vh));
      const maxShift = Math.max(0, track.scrollWidth - innerWidth + 48);
      track.style.transform = "translate3d(" + (-p * maxShift).toFixed(1) + "px,0,0)";
      for (const c of cards) {
        const img = c.querySelector("img");
        if (img) img.style.transform = "translate3d(" + ((p - 0.5) * -40).toFixed(1) + "px,0,0) scale(1.14)";
      }
    }
    if (fin) {
      const r = fin.getBoundingClientRect();
      const e = easeOut(clamp01((vh * 0.95 - r.top) / (vh * 0.6)));
      fin.style.transform = "scale(" + (0.9 + 0.1 * e).toFixed(3) + ")";
      fin.style.opacity = String(0.2 + 0.8 * e);
    }
  }
  const queue = () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  document.addEventListener("plunge:unlocked", queue);
  update();
}
