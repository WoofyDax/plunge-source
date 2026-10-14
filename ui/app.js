"use strict";
// The app's private bridge must never be reachable from a web page: block every way this page could navigate away or open one.
document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("a[href]"); if (a && !(a.getAttribute("href") || "").startsWith("#")) e.preventDefault(); }, true);
document.addEventListener("submit", e => e.preventDefault(), true);
window.open = () => null;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const S = { games: [], demo: false, sys: {}, disc: null, page: "discover", createApp: null, prefs: null,
            choices: null, active: {}, libFilter: "all", cur: null, polls: 0 };

const ENGINE = { unreal: "Unreal", unity: "Unity", godot: "Godot", emulator: "Emulator", other: "Other engine" };
const TIER = { native: "Native VR", injected: "Injected 3D", theater: "Virtual screen" };
// Steam artwork only exists for numeric Steam ids; other games get the letter tile
const steam = (id, f) => /^\d+$/.test(String(id)) ? `https://cdn.cloudflare.steamstatic.com/steam/apps/${id}/${f}` : "";
const hero = id => steam(id, "library_hero.jpg"), head = id => steam(id, "header.jpg"), cover = id => steam(id, "library_600x900.jpg");

/* ---------- helpers ---------- */
async function api(name, ...args) {
  if (!window.pywebview) throw new Error("Plunge must be opened as the desktop app");
  const r = await window.pywebview.api[name](...args);
  if (r && r.error) throw new Error(r.error);
  return r;
}
let toastTimer;
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.classList.toggle("bad", !!bad); t.classList.add("on");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 3800);
}
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  kids.flat().forEach(k => k != null && e.append(k));
  return e;
}
function icon(name, cls = "") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "i " + cls);
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", "#i-" + name); s.append(u); return s;
}
function bg(node, ...urls) {            // try each image in turn, fall back to a letter tile
  const [u, ...rest] = urls;
  if (!u) { node.classList.add("fb"); return node; }
  const im = new Image();
  im.onload = () => { node.style.backgroundImage = `url(${u})`; node.classList.remove("fb"); };
  im.onerror = () => bg(node, ...rest);
  im.src = u; return node;
}
const btn = (cls, label, ic, on) => el("button", { class: "btn " + cls, on: { click: guard(on) } }, ic ? icon(ic) : null, label);
const vrLevel = g => g.vr && g.vr.level;
const isQuick = g => g.status === "supported" && !vrLevel(g);
const activeProfile = g => S.active[g.appid] || (g.profiles && g.profiles[0] && g.profiles[0].slug) || null;

/* ---------- cards & rows ---------- */
function gameCard(g, onClick) {
  const shot = bg(el("div", { class: "shot", "data-t": g.name[0] }), head(g.appid));
  if (g.status === "blocked" && vrLevel(g)) shot.append(el("span", { class: "pill vr" }, icon("vr"), "Built-in VR"));
  else if (g.status === "blocked") shot.append(el("span", { class: "pill blocked" }, icon("shield"), "Blocked"));
  else if (g.installed) shot.append(el("span", { class: "pill vr" }, icon("vr"), "VR on"));
  else if (vrLevel(g)) shot.append(el("span", { class: "pill vr" }, icon("vr"), vrLevel(g) === "only" ? "VR only" : "VR ready"));
  else if (isQuick(g)) shot.append(el("span", { class: "pill" }, icon("bolt"), "Quick try"));
  const sub = g.customized ? "Customized" : (g.store && g.store !== "Steam" ? g.store : ENGINE[g.engine]);
  const open = typeof onClick === "function" ? onClick : () => openGame(g.appid);
  return el("button", { class: "card", on: { click: guard(open) } }, shot, el("div", { class: "meta" }, el("b", {}, g.name), el("span", {}, sub)));
}
function profileCard(r) {
  const shot = bg(el("div", { class: "shot", "data-t": (r.title || "?")[0] }), head(r.steamAppId));
  shot.append(el("span", { class: "pill" }, r.version ? "v" + r.version : TIER[r.tier] || "VR"));
  if (r.owned) shot.append(el("span", { class: "pill right vr" }, icon("check"), "In library"));
  return el("button", { class: "card", on: { click: guard(() => openHubProfile(r)) } }, shot,
    el("div", { class: "meta" }, el("b", {}, r.title), el("span", {}, `${r.author || "unknown"} · ${TIER[r.tier] || r.tier}`)));
}
function adCard(a) {
  const shot = el("div", { class: "shot" }); if (a.image) shot.style.backgroundImage = `url(${a.image})`; else shot.classList.add("fb"), shot.dataset.t = (a.title || "?")[0];
  shot.append(el("span", { class: "pill" }, "Sponsored"));
  const card = el("button", { class: "card", on: { click: guard(() => api("ad_click", a.id)) } }, shot,
    el("div", { class: "meta" }, el("b", {}, a.title), el("span", {}, [a.advertiser, a.body || a.cta].filter(Boolean).join(" · "))));
  if (!card.dataset.seen) { card.dataset.seen = "1"; setTimeout(() => api("ad_seen", a.id).catch(() => {}), 1200); }
  return card;
}
function rowSection(title, nodes, empty) {
  const frag = document.createDocumentFragment();
  frag.append(el("h2", { class: "sec" }, title));
  if (!nodes.length) { frag.append(empty || el("div", { class: "empty" }, "Nothing here yet.")); return frag; }
  const row = el("div", { class: "row" }, nodes);
  const wrap = el("div", { class: "row-wrap" }, row);
  const go = d => row.scrollBy({ left: d * row.clientWidth * 0.9, behavior: "smooth" });
  if (nodes.length > 3) {
    const r = el("button", { class: "arrow", "aria-label": "Scroll right", on: { click: () => go(1) } }, icon("right"));
    const l = el("button", { class: "arrow l", "aria-label": "Scroll left", hidden: true, on: { click: () => go(-1) } }, icon("left"));
    const sync = () => { l.hidden = row.scrollLeft < 8; r.hidden = row.scrollLeft + row.clientWidth > row.scrollWidth - 8; };
    row.addEventListener("scroll", sync);
    wrap.append(r, l);
  }
  frag.append(wrap); return frag;
}

/* ---------- Discover ---------- */
let heroTimer;
function heroSlides() {
  const feat = (S.disc && S.disc.featured) || [];
  if (feat.length) return feat.map(r => ({ kind: "hub", r, appid: r.steamAppId, title: r.title, by: r.author || "unknown",
    label: r.owned ? "Open" : "Add to Library", ic: r.owned ? "play" : "plus", run: () => openHubProfile(r) }));
  const pick = [...S.games.filter(g => vrLevel(g) && g.status !== "blocked"), ...S.games.filter(isQuick), ...S.games.filter(g => g.status === "experimental")]
    .filter((g, i, a) => a.findIndex(x => x.appid === g.appid) === i).slice(0, 3);
  return pick.map(g => ({ kind: "game", g, appid: g.appid, title: g.name,
    by: vrLevel(g) ? "Has built-in VR support. Customize it your way." : isQuick(g) ? "Try it in VR right now with UEVR" : "Have an AI agent build its VR version",
    label: vrLevel(g) ? "Customize" : "Open", ic: vrLevel(g) ? "sliders" : "play", run: () => openGame(g.appid) }));
}
function renderHero() {
  const h = $("#hero"); h.replaceChildren(); clearInterval(heroTimer);
  const slides = heroSlides();
  if (!slides.length) {
    h.append(el("div", { class: "slide on", style: "background:linear-gradient(120deg,#1b2a44,#141414)" },
      el("div", {}, el("h2", {}, "Play your games in VR"), el("div", { class: "by" }, "Install Steam games to get started."))));
    return;
  }
  const els = slides.map((s, i) => {
    const slide = bg(el("div", { class: "slide" + (i ? "" : " on") }), hero(s.appid), head(s.appid));
    const pair = el("div", { class: "pair" }, bg(el("div", { class: "ic" }), cover(s.appid)), el("span", { class: "plus" }, "+"),
      el("div", { class: "ic", style: "background:#168bff" }, icon("vr")));
    slide.append(el("div", {}, pair, el("h2", {}, s.title), el("div", { class: "by" }, s.by), btn("blue", s.label, s.ic, s.run)));
    h.append(slide); return slide;
  });
  let cur = 0;
  const dots = el("div", { class: "dots" }, slides.map((_, i) => el("button", { "aria-label": "Slide " + (i + 1), class: i ? "" : "on", on: { click: () => show(i) } })));
  const show = i => { cur = i; els.forEach((e, j) => e.classList.toggle("on", j === i)); $$("button", dots).forEach((d, j) => d.classList.toggle("on", j === i)); };
  if (slides.length > 1) { h.append(dots); heroTimer = setInterval(() => show((cur + 1) % slides.length), 7000); }
}
/* open games: public ones listed, private ones joined with a code */
function openGamesSection() {
  const frag = document.createDocumentFragment();
  const o = S.open, rows = (o && o.lobbies) || [];
  frag.append(el("h2", { class: "sec" }, "Open games right now"));
  const nameOf = l => { const g = S.games.find(x => x.appid === String(l.appid)); return g ? g.name : l.title; };
  const cards = rows.map(l => el("div", { class: "lobby", style: "background:var(--card);padding:12px 14px;border-radius:14px" },
    el("div", { style: "flex:1" }, el("b", {}, l.title), el("span", { class: "muted", style: "display:block;font-size:13px" }, `${nameOf(l)} · ${l.players}/${l.maxPlayers} players`)),
    btn("blue sm", "Join", "users", () => joinCode(l.code))));
  const code = el("input", { class: "input", placeholder: "Join code", "aria-label": "Private game join code", maxlength: "12", style: "width:130px;text-transform:uppercase" });
  const priv = el("div", { class: "lobby", style: "background:var(--card);padding:12px 14px;border-radius:14px" },
    el("div", { style: "flex:1" }, el("b", {}, "Private games"), el("span", { class: "muted", style: "display:block;font-size:13px" }, o ? `${o.privateCount} running now. Friends share a code or invite link with you.` : "Friends share a code or invite link with you.")),
    code, btn("dark sm", "Join", "users", async () => { if (!code.value.trim()) return toast("Type the code first", true); await joinCode(code.value.trim()); }));
  frag.append(el("div", { style: "display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))" }, ...cards, priv));
  if (!rows.length) frag.append(el("p", { class: "muted", style: "font-size:14px;margin-top:8px" }, o ? "No public games are open right now. Host one from any multiplayer build and tick “List publicly”." : "Couldn’t reach the lobby service. Private codes still work once it’s back."));
  return frag;
}

/* search + filters over every build on the hub */
const DQ = { text: "", game: "", sort: "new", tier: "", mp: false, mine: false };
const dqActive = () => !!(DQ.text.trim() || DQ.game || DQ.tier || DQ.mp || DQ.mine || DQ.sort !== "new");
let dqTimer, dqSeq = 0;
function discoverBar(results) {
  const gameNames = new Map();
  for (const r of [...((S.disc && S.disc.released) || []), ...((S.disc && S.disc.popular) || []), ...results]) {
    const mine = S.games.find(g => g.appid === String(r.steamAppId));
    gameNames.set(String(r.steamAppId), mine ? mine.name : r.title.replace(/\s+VR$/i, ""));
  }
  const inp = el("input", { class: "input", id: "dqText", placeholder: "Search VR builds, games or creators", "aria-label": "Search VR builds", value: DQ.text, style: "flex:1;min-width:220px",
    on: { input: e => { DQ.text = e.target.value; clearTimeout(dqTimer); dqTimer = setTimeout(runDiscover, 300); } } });
  const sel = (label, key, opts) => el("select", { class: "input", "aria-label": label, style: "width:auto", on: { change: e => { DQ[key] = e.target.value; runDiscover(); } } },
    opts.map(([v, l]) => el("option", { value: v, selected: v === DQ[key] }, l)));
  const chip = (label, key) => el("button", { class: "chip" + (DQ[key] ? " on" : ""), role: "switch", "aria-checked": String(!!DQ[key]), on: { click: () => { DQ[key] = !DQ[key]; runDiscover(); } } }, label);
  return el("div", { style: "display:grid;gap:10px;margin:6px 0 14px" },
    el("div", { style: "display:flex;gap:10px;flex-wrap:wrap" }, inp,
      sel("Game", "game", [["", "All games"], ...[...gameNames].sort((a, b) => a[1].localeCompare(b[1])).map(([id, n]) => [id, n])]),
      sel("Sort", "sort", [["new", "Newest"], ["popular", "Most popular"], ["liked", "Most liked"], ["featured", "Featured"]]),
      sel("Type", "tier", [["", "Any type"], ["native", "Native VR"], ["injected", "Injected 3D"], ["theater", "Virtual screen"]])),
    el("div", { style: "display:flex;gap:8px;flex-wrap:wrap;align-items:center" }, chip("Multiplayer", "mp"), chip("Only games I own", "mine"),
      dqActive() ? el("button", { class: "chip", on: { click: () => { Object.assign(DQ, { text: "", game: "", sort: "new", tier: "", mp: false, mine: false }); runDiscover(); } } }, icon("x"), "Clear filters") : null));
}
async function runDiscover() {
  const my = ++dqSeq;
  if (!dqActive()) { S.dres = null; return renderDiscover(); }
  let res = { profiles: [] }, err = null;
  try { res = await api("discover_browse", DQ.text, DQ.game, DQ.sort, DQ.tier, DQ.mp, DQ.mine); } catch (e) { err = e.message; }
  if (my !== dqSeq) return;                               // a newer search has started: ignore this answer
  S.dres = { rows: res.profiles, err };
  renderDiscover();
  const t = $("#dqText"); if (t && document.activeElement !== t && DQ.text) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
}
function renderDiscover() {
  renderHero();
  const box = $("#discoverRows"); box.replaceChildren();
  const results = (S.dres && S.dres.rows) || [];
  box.append(discoverBar(results));
  if (dqActive() && S.dres) {
    if (S.dres.err) box.append(el("div", { class: "empty" }, S.dres.err));
    else box.append(el("h2", { class: "sec" }, `${results.length} build${results.length === 1 ? "" : "s"}`),
      results.length ? el("div", { class: "grid" }, results.map(profileCard)) : el("div", { class: "empty" }, el("b", {}, "No builds match"), "Try fewer filters, or build this one yourself."));
    return;
  }
  const d = S.disc || { released: [], popular: [] };
  if (d.hubError) box.append(el("p", { class: "muted", style: "margin-top:14px" }, "The Plunge hub is offline, so you’re seeing your own library. (" + d.hubError + ")"));
  const emptyHub = el("div", { class: "empty" }, el("b", {}, "No VR builds published yet"), "Make one for a game you love and share it with everyone.",
    btn("blue", "Create the first one", "plus", () => go("create")));
  box.append(openGamesSection());
  box.append(rowSection("Just released", d.released.map(profileCard), d.hubError ? el("div", { class: "empty" }, "The hub is offline.") : emptyHub));
  if (d.popular.length) box.append(rowSection("Popular", d.popular.map(profileCard)));
  const vr = S.games.filter(g => vrLevel(g));
  const quick = S.games.filter(isQuick);
  const vrCards = vr.map(g => gameCard(g));
  if (S.ad && S.ad.ad && vrCards.length) vrCards.splice(Math.min(2, vrCards.length), 0, adCard(S.ad.ad));   // one labelled sponsored card, only on Discover
  box.append(rowSection("Already VR-ready in your library", vrCards,
    el("div", { class: "empty" }, S.games.some(g => g.vr && g.vr.via === "checking") ? "Checking Steam for VR support…" : "None of your games advertise VR support.")));
  box.append(rowSection("Quick try with UEVR", quick.map(g => gameCard(g)), el("div", { class: "empty" }, "No Unreal Engine games found.")));
}

/* ---------- Library ---------- */
function renderLibrary() {
  const f = S.libFilter, body = $("#libBody"); body.replaceChildren();
  $$("#libFilters .chip[data-f]").forEach(c => c.classList.toggle("on", c.dataset.f === f));
  const test = { all: () => true, custom: g => g.customized || g.installed, vr: g => vrLevel(g), quick: isQuick, blocked: g => g.status === "blocked" }[f];
  const list = S.games.filter(test);
  if (f === "all") {
    const mine = list.filter(g => g.customized || g.installed);
    if (mine.length) { body.append(el("h2", { class: "sec" }, "My VR games"), el("div", { class: "grid" }, mine.map(g => gameCard(g)))); }
    body.append(el("h2", { class: "sec" }, "All games"));
  }
  body.append(list.length ? el("div", { class: "grid" }, list.map(g => gameCard(g))) : el("div", { class: "empty" }, "Nothing matches this filter."));
  if (S.demo) body.prepend(el("p", { class: "muted" }, "Steam not found: this is a demo library you can explore but not launch."));
}

/* ---------- Game sheet ---------- */
const sheet = $("#sheet");
sheet.addEventListener("click", e => { if (e.target === sheet) sheet.close(); });
async function openGame(appid) {
  const g = await api("game_info", appid);
  S.cur = g; if (!S.prefs || S.prefsFor !== appid) { S.prefs = g.preferences; S.prefsFor = appid; }
  drawGameSheet(); if (!sheet.open) sheet.showModal();
}
function playLabel(g, hasProfile) {
  if (g.demo) return "Demo entry";
  if (g.status === "blocked") return vrLevel(g) ? "Launch in VR (built-in, untouched)" : "Blocked: anti-cheat";
  if (hasProfile) return "Play in VR";
  if (vrLevel(g)) return "Play in VR";
  return isQuick(g) ? "Quick try with UEVR" : "Build a VR version first";
}
function drawGameSheet() {
  const g = S.cur, body = $("#sheetBody"); body.replaceChildren();
  const locked = g.status === "blocked";                          // anti-cheat: Plunge never installs or injects anything
  const slug = locked ? null : activeProfile(g), prof = g.profiles.find(p => p.slug === slug), mp = prof && prof.recipe && prof.recipe.multiplayer;
  const hero_ = bg(el("div", { class: "sheet-hero" }), hero(g.appid), head(g.appid));
  hero_.append(el("div", {}, el("div", { class: "pair" }, bg(el("div", { class: "ic" }), cover(g.appid)), el("span", { class: "plus" }, "+"), el("div", { class: "ic", style: "background:#168bff" }, icon("vr"))),
    el("h2", {}, g.name)));
  body.append(hero_, el("button", { class: "x", "aria-label": "Close", on: { click: () => sheet.close() } }, icon("x")));

  const chips = el("div", { class: "chips" }, el("span", { class: "chip" }, ENGINE[g.engine]));
  if (vrLevel(g)) chips.append(el("span", { class: "chip good" }, icon("vr"), (g.vr.level === "only" ? "VR only" : "Built-in VR support") + " · " + g.vr.via));
  if (g.anticheat.length) chips.append(el("span", { class: "chip" }, icon("shield"), g.anticheat.join(", ")));
  if (locked && vrLevel(g)) chips.append(el("span", { class: "chip", title: "Plunge starts it exactly as Steam would. Nothing is installed or changed." },
    icon("shield"), "Launched untouched: no customizing"));
  if (prof) chips.append(el("span", { class: "chip" }, TIER[prof.tier] || prof.tier));
  if (prof && prof.stale) chips.append(el("span", { class: "chip", style: "background:#4a3a12;color:#ffd27a", title: `Tested on build ${prof.builtFor}; you have ${prof.currentBuild}` },
    icon("shield"), "Game updated since this build was tested"));
  if (prof && prof.binaries.length) chips.append(el("span", { class: "chip" }, icon("shield"), `Runs ${prof.binaries.length} extra program${prof.binaries.length > 1 ? "s" : ""}`));

  const playBtn = el("button", { class: "btn blue", on: { click: guard(() => doPlay(slug, steps)) } }, icon("play"), playLabel(g, !!prof));
  playBtn.disabled = g.demo || (locked && !vrLevel(g)) || (!locked && !prof && !vrLevel(g) && !isQuick(g));
  const steps = el("div", { class: "stepper", hidden: true });
  const acts = el("div", { class: "actions" }, playBtn,
    locked ? null : btn("dark", "Customize", "sliders", () => { sheet.close(); go("create", g.appid); }),
    g.installed ? btn("dark sm", "Remove VR layer", "trash", doUninstall) : null);
  if (g.profiles.length > 1) acts.append(el("select", { class: "input", style: "width:auto", "aria-label": "VR build",
    on: { change: e => { S.active[g.appid] = e.target.value; drawGameSheet(); } } },
    g.profiles.map(p => el("option", { value: p.slug, selected: p.slug === slug }, p.title))));
  const sys = S.sys || {}, checks = el("div", { class: "box" }, el("h4", {}, "Ready check"));
  const chk = (ok, t, extra) => el("div", { class: "check" + (ok ? " ok" : "") }, el("i", {}, ok ? "✓" : ""), el("span", {}, t), extra || "");
  checks.append(chk(sys.headsetReady, "VR runtime detected"));
  if ((prof && prof.recipe && prof.recipe.runtime === "uevr") || (!prof && isQuick(g))) {
    checks.append(chk(sys.uevrInstalled, "UEVR injector installed", sys.uevrInstalled ? null : btn("dark sm", "Install", null, doInstallRuntime)));
  }
  checks.append(chk(!!prof, prof ? "Build: " + prof.title : "No VR build for this game yet"));
  const facts = el("ul", { class: "facts" }, ...[["Route", g.route.label], ["Executable", g.exe ? g.exe.split("\\").pop() : "not found"], ["Your preferences", g.customized ? "Customized" : "Default"]]
    .map(([k, v]) => el("li", {}, el("span", {}, k), el("b", {}, v))));
  const about = vrLevel(g)
    ? "This game already has official VR support. Plunge can launch it as it is, or help you customize it: controls, perspective and comfort."
    : g.why;
  const left = el("div", { class: "box" }, el("h4", {}, "About this game"), about ? el("p", { class: "muted", style: "font-size:14px" }, about) : null, facts);
  body.append(el("div", { class: "sheet-body" }, chips, acts, steps, el("div", { class: "two" }, left, checks), mp ? mpBox(g, slug, mp) : null));
}
const defaultPrefs = () => ({ perspective: "auto", comfort: { snapTurn: true, vignette: true, locomotion: "smooth", stance: "seated" }, bindingsMode: "auto", bindings: [], notes: "" });

/* a build that ships third-party programs needs the player's OK first */
function askTrust(p) {
  return new Promise(resolve => {
    const dlg = $("#trustDlg");
    // a real build can bundle hundreds of files (BepInEx alone is ~190): show them grouped by who made them
    const groups = new Map();
    for (const b of p.binaries) {
      const k = `${b.author}|${b.license}`;
      const g = groups.get(k) || { author: b.author, license: b.license, names: new Set(), urls: new Set(), n: 0 };
      g.names.add(b.name); g.urls.add(b.url); g.n++; groups.set(k, g);
    }
    $("#trustSummary").textContent = `${p.binaries.length} file${p.binaries.length === 1 ? "" : "s"} from ${groups.size} source${groups.size === 1 ? "" : "s"}`;
    $("#trustList").replaceChildren(...[...groups.values()].sort((a, b) => b.n - a.n).map(g =>
      el("li", { title: [...g.urls].join("\n") }, el("span", {}, `${g.author} · ${[...g.names].slice(0, 2).join(", ")}${g.names.size > 2 ? ` +${g.names.size - 2} more` : ""}`),
        el("b", {}, `${g.license} · ${g.n} file${g.n === 1 ? "" : "s"}`))));
    const done = v => { dlg.close(); $("#trustYes").onclick = $("#trustNo").onclick = null; resolve(v); };
    $("#trustYes").onclick = () => done(true); $("#trustNo").onclick = () => done(false);
    dlg.addEventListener("close", () => resolve(false), { once: true });
    dlg.showModal();
  });
}

async function doPlay(slug, steps) {
  const g = S.cur;
  const prof = g.profiles.find(p => p.slug === slug);
  if (prof && prof.binaries.length && !prof.trusted) {
    if (!(await askTrust(prof))) return;
    await api("trust_profile", slug); prof.trusted = true;
  }
  steps.hidden = false;
  const names = ["Installing the VR layer", "Starting the game", "Plunged in"];
  steps.replaceChildren(...names.map(n => el("div", {}, el("i"), n)));
  const mark = (i, c) => { steps.children[i].className = c; };
  mark(0, "run");
  try {
    if (!slug && !vrLevel(g) && !(S.sys && S.sys.uevrInstalled)) await doInstallRuntime(true);
    const r = await api("play", g.appid, slug, "solo", null, null);
    mark(0, "done"); mark(1, "done"); mark(2, "done"); toast(r.steps[r.steps.length - 1]);
    await refreshGames(); await openGame(g.appid);
  } catch (e) {
    mark(0, "err");
    steps.append(el("div", { class: "err", style: "display:block;line-height:1.4" }, e.message));   // stays on screen, unlike a toast
    throw e;
  }
}
const doUninstall = async () => {
  const r = await api("uninstall", S.cur.appid);
  toast(`Removed: ${r.removed} files deleted, ${r.restored} restored`);
  await refreshGames(); await openGame(S.cur.appid);
};
async function doInstallRuntime(quiet) {
  toast("Downloading UEVR…"); const r = await api("install_runtime");
  S.sys = await api("system"); if (!quiet) toast(`Installed UEVR ${r.version || ""}`); if (!quiet && S.cur) drawGameSheet();
}

/* multiplayer */
function mpBox(g, slug, mp) {
  const box = el("div", { class: "box" }, el("h4", {}, icon("users"), `Play together · up to ${mp.maxPlayers}`),
    mp.kind === "added" ? el("p", { class: "muted", style: "font-size:13px" }, "Multiplayer added by this build for a single-player game. Experimental: expect rough edges.") : null,
    el("p", { class: "muted", style: "font-size:13px" }, "Everyone needs their own copy of the game and this same build. Friends outside your home network need a way to reach you: a private network like Tailscale or ZeroTier, or the game’s own relay. Plunge can’t open your router."));
  const pub = el("input", { type: "checkbox", id: "mpPublic" });
  const out = el("div", { class: "actions" });
  const hostBtn = el("button", { class: "btn dark sm", on: { click: guard(async () => {
    hostBtn.disabled = true; toast("Starting the game and waiting for it to host…");
    try {
      const r = await api("host", g.appid, slug, pub.checked, null);
      if (r.needAddress) { out.replaceChildren(addrForm(g, slug, pub, out, r.suggest)); }
      else showCode(out, r.code, g, r.network ? `Friends reach you through your ${r.network} address (${r.address}).` : null);
    } finally { hostBtn.disabled = false; }
  }) } }, icon("play"), "Host a game");
  box.append(el("div", { class: "actions" }, hostBtn, el("label", { class: "muted", style: "display:flex;gap:8px;align-items:center;font-size:14px" }, pub, "List publicly")), out);
  const lob = el("div", { style: "display:grid;gap:8px" }); box.append(lob);
  api("lobbies", g.appid).then(({ lobbies }) => lobbies.forEach(l => lob.append(el("div", { class: "lobby" }, el("span", {}, `${l.title} · ${l.players}/${l.maxPlayers}`),
    btn("dark sm", "Join", "users", () => joinCode(l.code)))))).catch(() => {});
  return box;
}
function showCode(out, code, g, note) {
  out.replaceChildren(el("span", { class: "code" }, code), btn("dark sm", "Copy", "copy", async () => { await api("copy_text", code); toast("Code copied"); }),
    btn("dark sm", "Copy invite link", "copy", async () => { await api("copy_text", "https://plungevr.com/join/" + code); toast("Invite link copied. Friends who open it land in Plunge."); }),
    note ? el("span", { class: "muted", style: "font-size:13px;flex-basis:100%" }, note) : null,
    btn("dark sm", "Stop", "x", async () => { await api("stop_hosting", g.appid); out.replaceChildren(); }));
}
function addrForm(g, slug, pub, out, suggest) {
  const inp = el("input", { class: "input", placeholder: "host:port your game is hosting on", value: suggest || "", style: "flex:1" });
  return el("div", { class: "actions", style: "width:100%" }, inp, btn("blue sm", "Open lobby", null, async () => {
    const r = await api("publish_lobby", g.appid, slug, inp.value.trim(), pub.checked); showCode(out, r.code, g);
  }));
}
/* join: get the build if you don't have it, ask about its third-party files, then start the game on the host's address */
async function joinCode(code) {
  const info = await api("join_info", code);
  if (!info.ownsGame) throw new Error(`You need to own ${info.title || "this game"} first.`);
  if (!info.haveBuild) { toast("Getting the build this game needs…"); await api("get_profile", info.profile); await refreshGames(false); }
  const g = await api("game_info", info.appid), prof = g.profiles.find(p => p.slug === info.profile);
  if (prof && prof.binaries.length && !prof.trusted) {
    if (!(await askTrust(prof))) return;
    await api("trust_profile", info.profile);
  }
  const r = await api("join", code);
  if (r.manualAddress) { try { await api("copy_text", r.manualAddress); } catch (e) { /* the address is shown below anyway */ } toast(`Game started. Paste ${r.manualAddress} into its join screen (copied for you).`); }
  else toast(r.steps[r.steps.length - 1] || "Joining…");
}

/* ---------- hub profile sheet ---------- */
async function applyHub(r, onState) {
  const game = S.games.find(g => g.appid === String(r.steamAppId));
  if (!game) throw new Error("You need to own this game first. Add it to Steam, then it appears here.");
  if (game.status === "blocked") throw new Error("This game uses anti-cheat, so Plunge never changes it.");
  onState("Downloading…");
  if (!r.owned) { await api("get_profile", r.id); r.owned = true; }
  const info = await api("game_info", game.appid);
  const prof = info.profiles.find(p => p.slug === r.id);
  if (!prof) throw new Error("The download didn’t appear in your library. Try again.");
  if (prof.binaries.length && !prof.trusted) {
    onState("Waiting for your OK…");
    if (!(await askTrust(prof))) throw new Error("Cancelled. Nothing was changed in your game.");
    await api("trust_profile", r.id);
  }
  onState("Applying to your game…");
  const out = await api("apply_build", game.appid, r.id);
  await refreshGames(false);
  return out;
}
function openGamesBox(r) {
  const list = el("div", { style: "display:grid;gap:8px" }, el("span", { class: "muted", style: "font-size:14px" }, "Looking for open games…"));
  api("lobbies", r.steamAppId).then(({ lobbies }) => {
    const mine = lobbies.filter(l => l.profile === r.id);
    list.replaceChildren(...(mine.length ? mine.map(l => el("div", { class: "lobby" }, el("span", {}, `${l.title} · ${l.players}/${l.maxPlayers}`),
      btn("blue sm", "Join", "users", () => joinCode(l.code)))) : [el("span", { class: "muted", style: "font-size:14px" }, "No open games right now. Apply the build, then host one from the game’s page and send friends the invite link.")]));
  }).catch(() => list.replaceChildren(el("span", { class: "muted", style: "font-size:14px" }, "Couldn’t reach the lobby service.")));
  return el("div", { class: "box", style: "margin-top:14px" }, el("h4", {}, icon("users"), "Open games"), list);
}
async function openHubProfile(r) {
  const body = $("#sheetBody"); body.replaceChildren();
  const h = bg(el("div", { class: "sheet-hero" }), hero(r.steamAppId), head(r.steamAppId));
  h.append(el("div", {}, el("div", { class: "pair" }, bg(el("div", { class: "ic" }), cover(r.steamAppId)), el("span", { class: "plus" }, "+"), el("div", { class: "ic", style: "background:#168bff" }, icon("vr"))),
    el("h2", {}, r.title), el("div", { class: "by", style: "color:#d9d9de;margin-top:6px" }, "by " + (r.author || "unknown"))));
  const game = S.games.find(g => g.appid === String(r.steamAppId));
  let applied = false;
  try { applied = !!game && (await api("game_info", game.appid)).installedProfile === r.id; } catch (e) { /* the sheet still opens */ }
  const status = el("div", { class: "muted", style: "font-size:14px;min-height:20px" });
  const actions = el("div", { class: "actions" });
  const draw = () => {
    actions.replaceChildren();
    if (!game) { actions.append(el("span", { class: "muted" }, "You don’t own this game yet. Once it’s in your Steam library, you can add this build with one click.")); }
    else if (game.status === "blocked") { actions.append(el("span", { class: "muted" }, "This game uses anti-cheat, so Plunge never changes it.")); }
    else if (applied) {
      actions.append(btn("blue", "Play now", "play", async () => { status.textContent = "Starting the game…"; const o = await api("play", game.appid, r.id, "solo", null, null); status.textContent = o.steps[o.steps.length - 1]; }),
        btn("dark", "Remove it from my game", "trash", async () => { await api("uninstall", game.appid); applied = false; await refreshGames(false); status.textContent = "Removed. Your game is back exactly as it was."; draw(); }));
    } else {
      const go = btn("blue", "Download and apply to my game", "down", async () => {
        go.disabled = true;
        try { await applyHub(r, t => { status.textContent = t; }); applied = true; status.textContent = "Done. It’s applied to your game. Press Play now to try it."; draw(); }
        catch (e) { status.textContent = e.message; toast(e.message, true); go.disabled = false; }
      });
      actions.append(go);
    }
    actions.append(btn("dark", String(r.likes), "heart", async () => { if (!S.user) return needSignIn("Sign in to like builds"); await api("like", r.id); toast("Liked"); }));
  };
  draw();
  body.append(h, el("button", { class: "x", "aria-label": "Close", on: { click: () => sheet.close() } }, icon("x")),
    el("div", { class: "sheet-body" },
      el("p", { class: "muted" }, r.tagline || ""),
      el("div", { class: "chips" }, el("span", { class: "chip" }, TIER[r.tier] || r.tier), el("span", { class: "chip" }, "Comfort: " + r.comfort), el("span", { class: "chip" }, r.controls === "both" ? "Motion + gamepad" : r.controls + " controls"),
        r.multiplayer ? el("span", { class: "chip good" }, icon("users"), r.multiplayerKind === "added" ? "Multiplayer (added, experimental)" : "Multiplayer") : null, el("span", { class: "chip" }, `${r.downloads} downloads`)),
      actions, status, r.multiplayer ? openGamesBox(r) : null));
  if (!sheet.open) sheet.showModal();
}

/* ---------- Create ---------- */
const saveDebounced = (() => { let t; return () => { clearTimeout(t); $("#savedNote") && ($("#savedNote").textContent = "Saving…");
  t = setTimeout(guard(async () => { await api("save_prefs", S.createApp, S.prefs); $("#savedNote") && ($("#savedNote").textContent = "Saved"); await refreshGames(false); }), 500); }; })();

async function renderCreate() {
  const body = $("#createBody"); body.replaceChildren();
  if (!S.createApp) {
    $("#createTitle").textContent = "Create";
    const q = el("input", { class: "input", placeholder: "Pick a game to customize or build a VR version of", style: "max-width:520px", "aria-label": "Filter games" });
    const grid = el("div", { class: "grid", style: "margin-top:18px" });
    const draw = () => { grid.replaceChildren(...S.games.filter(g => g.name.toLowerCase().includes(q.value.toLowerCase())).map(g => {
      return gameCard(g, () => go("create", g.appid)); })); };
    q.addEventListener("input", draw); draw();
    body.append(q, grid); return;
  }
  const g = await api("game_info", S.createApp); S.cur = g;
  if (g.status === "blocked") {                      // anti-cheat: Plunge never modifies these
    $("#createTitle").replaceChildren(g.name);
    body.append(el("div", { class: "empty" }, icon("shield"), el("b", {}, "This game uses anti-cheat"),
      "Plunge never changes games with anti-cheat: any VR layer would be flagged by it and could get your account banned.",
      vrLevel(g) ? "It already has official VR support, so you can launch it exactly as it is from your library." : "",
      btn("blue", "Pick another game", "left", () => go("create", null))));
    return;
  }
  if (S.prefsFor !== g.appid || !S.prefs) { S.prefs = g.preferences; S.prefsFor = g.appid; }
  S.choices = S.choices || await api("input_choices");
  $("#createTitle").replaceChildren(g.name);
  const P = S.prefs, C = S.choices;
  const seg = (opts, val, on) => el("div", { class: "seg", role: "group" }, opts.map(([v, l]) => el("button", { class: v === val ? "on" : "", on: { click: e => { on(v); $$("button", e.target.parentElement).forEach(b => b.classList.toggle("on", b === e.target)); saveDebounced(); } } }, l)));
  const toggle = (label, key) => el("div", { class: "toggle", role: "switch", tabindex: "0", "aria-checked": String(P.comfort[key]),
    on: { click: e => { P.comfort[key] = !P.comfort[key]; e.currentTarget.setAttribute("aria-checked", String(P.comfort[key])); saveDebounced(); },
          keydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.currentTarget.click(); } } } }, el("span", {}, label), el("span", { class: "sw" }));

  const binds = el("div", { style: "display:grid;gap:8px" });
  const drawBinds = () => {
    binds.replaceChildren(...P.bindings.map((b, i) => el("div", { class: "bind" },
      el("select", { class: "input", "aria-label": "Controller input", on: { change: e => { b.input = e.target.value; saveDebounced(); } } }, C.inputs.map(x => el("option", { value: x, selected: x === b.input }, x))),
      el("span", { class: "arrowc" }, icon("right")),
      el("input", { class: "input", value: b.action, placeholder: "e.g. Reload, Sprint, Open map", "aria-label": "Action", on: { input: e => { b.action = e.target.value; saveDebounced(); } } }),
      el("button", { class: "icon-btn", "aria-label": "Remove binding", on: { click: () => { P.bindings.splice(i, 1); drawBinds(); saveDebounced(); } } }, icon("trash")))));
    binds.append(btn("dark sm", "Add a binding", "plus", () => { const used = new Set(P.bindings.map(b => b.input)); P.bindings.push({ input: C.inputs.find(x => !used.has(x)) || C.inputs[0], action: "" }); drawBinds(); }));
  };
  drawBinds();
  const bindsWrap = el("div", { style: "display:grid;gap:8px", hidden: P.bindingsMode === "auto" },
    el("span", { class: "muted", style: "font-size:13px" }, "Put any action on any button, even ones the game doesn’t normally use."), binds);
  const autoToggle = el("div", { class: "toggle", role: "switch", tabindex: "0", "aria-checked": String(P.bindingsMode === "auto"),
    on: { click: e => { P.bindingsMode = P.bindingsMode === "auto" ? "custom" : "auto"; e.currentTarget.setAttribute("aria-checked", String(P.bindingsMode === "auto"));
      bindsWrap.hidden = P.bindingsMode === "auto"; saveDebounced(); },
          keydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.currentTarget.click(); } } } },
    el("span", {}, "Let the VR build decide the controls"), el("span", { class: "sw" }));

  const custom = el("div", { class: "box" }, el("h4", {}, icon("sliders"), "Your preferences"),
    el("p", { class: "muted", style: "font-size:14px" }, "Tell the VR build how you want to play. These go into your AI brief, and builds that support them read them every time you press Play."),
    el("div", { class: "field" }, el("label", {}, "Camera"), seg(Object.entries(C.perspectives), P.perspective, v => P.perspective = v)),
    el("div", { class: "field" }, el("label", {}, "Movement"), seg(C.locomotion.map(x => [x, x[0].toUpperCase() + x.slice(1)]), P.comfort.locomotion, v => P.comfort.locomotion = v)),
    el("div", { class: "field" }, el("label", {}, "Stance"), seg(C.stance.map(x => [x, x[0].toUpperCase() + x.slice(1)]), P.comfort.stance, v => P.comfort.stance = v)),
    toggle("Snap turning", "snapTurn"), toggle("Comfort vignette", "vignette"),
    el("div", { class: "field" }, el("label", {}, "Controller bindings"), autoToggle, bindsWrap),
    el("div", { class: "field" }, el("label", {}, "Anything else?"),
      el("textarea", { class: "input", placeholder: "e.g. keep the camera over the shoulder in cars, no head bob, big readable subtitles…", on: { input: e => { P.notes = e.target.value; saveDebounced(); } } }, P.notes)),
    el("div", { class: "saved", id: "savedNote" }, ""));

  const sys = S.sys || {};
  const build = el("div", { class: "box" }, el("h4", {}, icon("spark"), "Build with AI"));
  if (vrLevel(g)) build.append(el("span", { class: "chip good", style: "justify-self:start" }, icon("vr"), "Already has VR support · " + g.vr.via));
  build.append(el("p", { class: "muted", style: "font-size:14px" }, vrLevel(g)
    ? "This game already supports VR. The agent builds on top of it: your controls, comfort and perspective."
    : "An AI agent reads the game, redesigns it for VR with your preferences, tests it and saves a build here."),
    el("div", { class: "toggle", role: "switch", tabindex: "0", "aria-checked": String(P.interview === "ask"),
      on: { click: e => { P.interview = P.interview === "ask" ? "skip" : "ask"; e.currentTarget.setAttribute("aria-checked", String(P.interview === "ask"));
              $("#interviewNote").textContent = P.interview === "ask" ? "It will ask about five short questions, then build." : "Off: it just builds with sensible defaults and tells you what it picked."; saveDebounced(); },
            keydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.currentTarget.click(); } } } },
      el("span", {}, "Let the agent ask me questions first"), el("span", { class: "sw" })),
    el("p", { id: "interviewNote", class: "muted", style: "font-size:13px;margin-top:-6px" }, P.interview === "ask" ? "It will ask about five short questions, then build." : "Off: it just builds with sensible defaults and tells you what it picked."),
    btn(P.guided ? "dark block" : "blue block", P.guided ? "Redo the guided setup" : "Start guided setup", "spark", () => openWizard(g.appid)),
    btn("dark block", "Skip the questions: send to my AI agent", "play", () => openAgentDialog(g.appid)),
    btn("dark block", "Copy the brief instead", "copy", copyBrief),
    btn("dark block", "Connect Plunge to my AI tools", "bolt", openConnect),
    el("p", { class: "muted", style: "font-size:13px;text-align:center" }, "Plunge finds Claude Code, Codex, Gemini CLI and others on this PC and starts one for you."));
  const mine = el("div", { class: "box" }, el("h4", {}, icon("stack"), "Your builds for this game"));
  if (!g.profiles.length) mine.append(el("p", { class: "muted", style: "font-size:14px" }, "None yet. Once your agent saves one it shows up here."));
  g.profiles.forEach(p => mine.append(el("div", { class: "prow" }, el("div", {}, el("b", {}, p.title), el("span", { class: "muted", style: "font-size:13px" }, `${TIER[p.tier] || p.tier} · comfort ${p.comfort}`)),
    btn("dark sm", "Check", "check", async () => { const r = await api("validate", p.slug, g.appid); toast(r.ok ? "Build is clean" : r.findings[0].msg, !r.ok); }),
    btn("dark sm", "Publish", "up", async () => { if (!S.user) return needSignIn("Sign in to publish"); toast("Publishing…"); await api("publish", p.slug); toast(`Published as ${S.user.username}`); S.disc = null; }))));
  mine.append(btn("dark block", "Open this game", "play", () => openGame(g.appid)));
  body.append(el("p", { class: "muted", style: "margin:-8px 0 18px" }, el("button", { class: "chip", on: { click: () => go("create", null) } }, icon("left"), "Change game")),
    el("div", { class: "create-grid" }, custom, el("div", { style: "display:grid;gap:20px" }, build, mine)));
  S.wizardAsked = S.wizardAsked || {};
  if (!P.guided && !S.wizardAsked[g.appid]) { S.wizardAsked[g.appid] = true; setTimeout(() => { if (S.page === "create" && S.createApp === g.appid) openWizard(g.appid); }, 200); }   // the questions come first, by default
}
const copyBrief = async () => {
  const { prompt } = await api("prompt", S.createApp || S.cur.appid);
  try { await api("copy_text", prompt); toast("Brief copied. Paste it into Claude Code or Codex."); }
  catch { $("#promptText").value = prompt; $("#promptDlg").showModal(); }
};


/* ---------- guided setup: one question at a time ---------- */
async function openWizard(appid) {
  const g = S.cur && S.cur.appid === String(appid) ? S.cur : await api("game_info", appid);
  if (S.prefsFor !== g.appid || !S.prefs) { S.prefs = g.preferences; S.prefsFor = g.appid; }
  S.choices = S.choices || await api("input_choices");
  S.createApp = g.appid;
  const P = S.prefs, C = S.choices, dlg = $("#wizardDlg"), body = $("#wizardBody");
  P.comfort = P.comfort || {};
  const steps = [
    { q: "How do you want to see the game?", help: "This is the camera.", get: () => P.perspective, set: v => P.perspective = v,
      opts: [["auto", "Let the VR build decide", "Best for most games"], ["first", "First person", "You look out through the character’s eyes"], ["third", "Keep third person", "You see the character; VR moves the camera and aim"]] },
    { q: "How do you want to move around?", help: "Smooth is like a normal game. Teleport is gentler if you get motion sick.", get: () => P.comfort.locomotion, set: v => P.comfort.locomotion = v,
      opts: [["smooth", "Smooth movement", "Walk with the thumbstick"], ["teleport", "Teleport", "Point and jump to a spot; easiest on your stomach"], ["room-scale only", "Room-scale only", "You move by walking around your play space"]] },
    { q: "Will you be sitting or standing?", help: "The build sets your height to match.", get: () => P.comfort.stance, set: v => P.comfort.stance = v,
      opts: [["seated", "Sitting", "Chair, couch or desk"], ["standing", "Standing", "On your feet with room to move"]] },
    { q: "Turn in steps instead of smoothly?", help: "Snap turning jumps your view a set angle at a time. Many people find it more comfortable.", get: () => P.comfort.snapTurn, set: v => P.comfort.snapTurn = v,
      opts: [[true, "Yes, snap turning", "Recommended if you get motion sick"], [false, "No, turn smoothly", ""]] },
    { q: "Darken the edges while you move?", help: "A comfort vignette narrows your view during movement and cuts motion sickness.", get: () => P.comfort.vignette, set: v => P.comfort.vignette = v,
      opts: [[true, "Yes, use a vignette", "Recommended"], [false, "No, keep the full view", ""]] },
    { q: "How should the controllers work?", help: "You can always change this later.", get: () => P.bindingsMode, set: v => P.bindingsMode = v,
      opts: [["auto", "Let the VR build decide", "It picks sensible controls for this game"], ["custom", "I’ll choose some buttons myself", "Put any action on any button"]],
      extra: (box) => {
        if (P.bindingsMode !== "custom") return;
        const list = el("div", { style: "display:grid;gap:8px" });
        const draw = () => {
          list.replaceChildren(...P.bindings.map((b, i) => el("div", { class: "bind" },
            el("select", { class: "input", "aria-label": "Controller input", on: { change: e => { b.input = e.target.value; } } }, C.inputs.map(x => el("option", { value: x, selected: x === b.input }, x))),
            el("span", { class: "arrowc" }, icon("right")),
            el("input", { class: "input", value: b.action, placeholder: "e.g. Reload, Sprint, Open map", "aria-label": "Action", on: { input: e => { b.action = e.target.value; } } }),
            el("button", { class: "icon-btn", "aria-label": "Remove binding", on: { click: () => { P.bindings.splice(i, 1); draw(); } } }, icon("trash")))),
            btn("dark sm", "Add a binding", "plus", () => { const used = new Set(P.bindings.map(b => b.input)); P.bindings.push({ input: C.inputs.find(x => !used.has(x)) || C.inputs[0], action: "" }); draw(); }));
        };
        draw(); box.append(list);
      } },
    { q: "Do you want to play it with friends?", help: "Each friend needs their own copy of the game. Plunge gives you a join code.", get: () => P.multiplayer || "no", set: v => P.multiplayer = v,
      opts: [["no", "Just me", "Single player"], ["supported", "Yes, if the game already has multiplayer", "The build uses the game’s own multiplayer"],
             ["add", "Yes, even if it’s single-player (experimental)", "The AI tries to build a co-op layer. It can’t work for every game, and it will tell you honestly what it managed."]] },
    { q: "Anything else the build should know?", help: "Optional. For example: keep the camera over the shoulder in cars, no head bob, big readable subtitles.", text: true },
    { q: "Should the AI ask you questions first?", help: "It would ask about five short questions before it builds. Or it can just start with sensible defaults.", get: () => P.interview || "skip", set: v => P.interview = v,
      opts: [["skip", "No, just build it", "It tells you what it chose"], ["ask", "Yes, ask me first", "Good if this game is unusual"]] },
  ];
  const total = steps.length + 1;                                   // the last page is the summary
  let n = 0;
  const label = (st, v) => { const o = (st.opts || []).find(x => x[0] === v); return o ? o[1] : String(v); };
  async function persist() { await api("save_prefs", g.appid, P); await refreshGames(false); }
  async function next() { n = Math.min(n + 1, steps.length); if (n === steps.length) P.guided = true; await persist(); draw(); }
  function draw() {
    const last = n === steps.length, st = steps[n];
    const top = el("div", { class: "wiz-top" }, el("span", {}, last ? "All set" : `Question ${n + 1} of ${steps.length}`),
      el("button", { class: "icon-btn", "aria-label": "Close", on: { click: () => dlg.close() } }, icon("x")));
    const bar = el("div", { class: "wiz-bar" }, el("i", { style: `width:${Math.round((n + 1) / total * 100)}%` }));
    const nodes = [top, bar];
    if (last) {
      nodes.push(el("h2", { class: "wiz-q" }, "Ready to build"), el("p", { class: "wiz-help" }, "Here is what you picked. Press Send and your AI agent builds it for you."),
        el("div", { class: "wiz-sum" }, ...steps.filter(s => !s.text).map(s => el("div", {}, el("span", {}, s.q.replace(/\?$/, "")), el("b", {}, label(s, s.get())))),
          P.notes ? el("div", {}, el("span", {}, "Extra notes"), el("b", {}, P.notes.slice(0, 40) + (P.notes.length > 40 ? "…" : ""))) : null));
    } else {
      nodes.push(el("h2", { class: "wiz-q" }, st.q), el("p", { class: "wiz-help" }, st.help));
      if (st.text) nodes.push(el("textarea", { class: "input", rows: "4", placeholder: "Leave empty to skip", "aria-label": st.q, on: { input: e => { P.notes = e.target.value; const nb = $(".wiz-foot .btn.blue", body); if (nb) nb.lastChild.textContent = P.notes.trim() ? "Next" : "Skip"; } } }, P.notes || ""));
      else {
        const opts = el("div", { class: "wiz-opts", role: "radiogroup" }), extra = el("div");
        const paint = () => opts.replaceChildren(...st.opts.map(([v, l, sub]) => el("button", { class: "agent-card" + (st.get() === v ? " on" : ""), role: "radio", "aria-checked": String(st.get() === v),
          on: { click: () => { st.set(v); if (st.extra && v === "custom") { paint(); extra.replaceChildren(); st.extra(extra); } else next(); } } },
          el("div", { style: "flex:1" }, el("b", {}, l), sub ? el("span", { class: "sub" }, sub) : null))));
        paint(); if (st.extra) st.extra(extra);
        nodes.push(opts, extra);
      }
    }
    const back = n > 0 ? btn("dark", "Back", "left", () => { n--; draw(); }) : el("span");
    const go = last ? btn("blue", "Send to my AI agent", "spark", async () => { await persist(); dlg.close(); openAgentDialog(g.appid); })
      : btn("blue", st.text && !P.notes ? "Skip" : "Next", "right", next);
    nodes.push(el("div", { class: "wiz-foot" }, back, go));
    body.replaceChildren(...nodes);
  }
  dlg.addEventListener("close", async () => { if (!P.guided) { P.guided = true; try { await persist(); } catch (e) { /* the page still works */ } } renderCreate(); }, { once: true });
  draw(); dlg.showModal();
}

/* ---------- connect Plunge's tools to the player's AI tools (one click each) ---------- */
async function openConnect() {
  const dlg = $("#connectDlg"), body = $("#connectBody");
  body.replaceChildren(el("p", { class: "muted" }, "Looking for your AI tools…")); if (!dlg.open) dlg.showModal();
  const st = await api("connect_status");
  const rows = st.tools.map(t => el("div", { class: "prow" }, el("div", {}, el("b", {}, t.name),
      el("span", { class: "muted", style: "font-size:13px" }, !t.found ? "Not found on this PC" : t.connected ? "Connected" : "Ready to connect")),
    t.found ? (t.connected
      ? btn("dark sm", "Disconnect", "x", async () => { const r = await api("disconnect_tool", t.id); toast(r.note || "Disconnected"); openConnect(); })
      : btn("blue sm", "Connect", "plus", async () => { const r = await api("connect_tool", t.id); toast(r.note || "Connected"); openConnect(); })) : null));
  body.replaceChildren(el("h3", {}, "Connect Plunge to your AI tools"),
    el("p", { class: "muted", style: "font-size:14px" }, "Once connected, your AI tool can use Plunge’s tools by itself: read a game, build the VR layer, test it and undo it. Nothing runs until you ask it to, and it still can’t touch games with anti-cheat. Plunge adds one entry called “plunge” to that tool’s settings (a backup is kept first)."),
    ...rows,
    el("div", { class: "box", style: "margin-top:10px" }, el("h4", {}, icon("copy"), "Another tool"),
      el("p", { class: "muted", style: "font-size:14px" }, "Any tool that supports MCP servers can use this entry."),
      btn("dark", "Copy the settings entry", "copy", async () => { await api("copy_text", st.snippet); toast("Copied. Paste it into that tool’s MCP settings."); })),
    el("div", { class: "actions" }, btn("blue", "Done", null, () => dlg.close())));
}

/* ---------- send the brief to the player's own AI agent ---------- */
function otherBox(dlg) {                                  // an agent Plunge doesn't know: copy the brief for it
  return el("div", { class: "box" }, el("h4", {}, icon("copy"), "Or another, if yours isn’t detected"),
    el("p", { class: "muted", style: "font-size:14px" }, "Copy the brief and paste it into your own AI coding agent. It has to run on your PC, because it needs to read and change the game’s files; a chat website can’t."),
    btn("dark", "Copy the brief", "copy", async () => { dlg.close(); await copyBrief(); }));
}
async function openAgentDialog(appid) {
  const body = $("#agentBody"), dlg = $("#agentDlg");
  body.replaceChildren(el("p", { class: "muted" }, "Looking for AI agents on this PC…")); if (!dlg.open) dlg.showModal();
  const { agents, saved } = await api("agents_detect");
  const found = agents.filter(a => a.found).sort((a, b) => (b.mode.startsWith("app") ? 1 : 0) - (a.mode.startsWith("app") ? 1 : 0));   // desktop apps first
  body.replaceChildren(el("h3", {}, "Send to an AI agent"));
  if (!found.length) {                                  // nothing installed: get one (needs a plan), or use any other AI by hand
    body.append(el("p", { class: "muted" }, "Plunge didn’t find an AI coding agent on this PC. Pick one of these:"),
      el("div", { class: "box" }, el("h4", {}, icon("spark"), "Get an AI agent"), el("p", { class: "muted", style: "font-size:14px" }, "Install one, then press “Check again”. They all need a subscription or API access from the company that makes them."),
        ...agents.filter(a => ["claude", "codex", "gemini", "grok"].includes(a.id)).map(a => el("div", { class: "prow" }, el("div", {}, el("b", {}, a.name)),
          btn("dark sm", "How to install", "up", () => api("open_url", a.install)), btn("dark sm", "Plans", "heart", () => api("open_url", a.plans))))),
      otherBox(dlg),
      el("div", { class: "actions" }, btn("dark", "Close", null, () => dlg.close()), btn("blue", "Check again", null, () => openAgentDialog(appid))));
    return;
  }
  const pick = { id: (found.find(a => saved && a.id === saved.provider) || found[0]).id, model: saved ? saved.model : "default", effort: saved ? saved.effort : "default", gameAccess: saved ? saved.gameAccess !== false : true, autoSend: true };
  const list = el("div", { style: "display:grid;gap:8px" }), controls = el("div", { style: "display:grid;gap:12px" });
  const preview = el("div", { class: "mono" }), notes = el("div", { class: "muted", style: "font-size:13px" });
  const startBtn = btn("blue", "Start", "play", async () => {
    const isApp = (found.find(x => x.id === pick.id) || {}).mode?.startsWith("app");
    if (isApp && pick.autoSend) { toast("Opening the app… keep this window alone for a few seconds."); startBtn.disabled = true; }
    const r = await api("agent_start", S.createApp || S.cur.appid, pick.id, pick.model, pick.effort, pick.gameAccess, !!pick.autoSend);
    dlg.close();
    if (r.sent === "sent") toast("Sent to the app. Check it and answer its questions.");
    else if (r.sent) toast(r.sent === "app-not-found" ? "The app didn’t open in time, so nothing was typed. Paste with Ctrl+V and press Enter." : "The app wasn’t in front, so Plunge typed nothing. Click its message box, paste with Ctrl+V and press Enter.");
    else toast(r.mode === "app" ? "Opened in the Claude app with the message ready. Check it, then press Enter."
      : r.pasted ? "Opened. Paste the first message with Ctrl+V." : "Opened in a new window. Your agent will ask before it changes anything.");
  });
  const refresh = guard(async () => {
    try { const p = await api("agent_preview", S.createApp || S.cur.appid, pick.id, pick.model, pick.effort, pick.gameAccess);
      preview.textContent = p.command; notes.textContent = (["paste", "app-paste", "editor"].includes(p.mode) ? "This one can’t take a first message from outside, so Plunge opens it and puts one line on your clipboard: press Ctrl+V and Enter. " : "") + p.notes.join(" "); startBtn.disabled = false; }
    catch (e) { preview.textContent = ""; notes.textContent = e.message; startBtn.disabled = true; }
  });
  const draw = () => {
    const a = found.find(x => x.id === pick.id);
    list.replaceChildren(...found.map(x => el("button", { class: "agent-card" + (x.id === pick.id ? " on" : ""), role: "radio", "aria-checked": String(x.id === pick.id),
      on: { click: () => { pick.id = x.id; pick.model = "default"; pick.effort = "default"; draw(); } } },
      el("div", { style: "flex:1" }, el("b", {}, x.name), el("span", { class: "sub" }, `${x.version || "installed"}${x.where && x.where !== "this PC" ? " · from the " + x.where : ""} · ${{ auto: "starts it and sends the message for you", app: "opens the app with the message filled in", "app-paste": "opens the app; you paste one line", editor: "opens the folder; you paste one line in its AI chat" }[x.mode] || "opens it; you paste one line"}`)))));
    const modelOpts = a.models.map(m => el("option", { value: m.id, selected: m.id === pick.model }, m.label));
    const custom = !a.models.some(m => m.id === pick.model);
    modelOpts.push(el("option", { value: "__other", selected: custom }, "Other…"));
    const modelSel = el("select", { class: "input", "aria-label": "Model", on: { change: e => { if (e.target.value === "__other") { pick.model = ""; customInp.hidden = false; customInp.focus(); } else { pick.model = e.target.value; customInp.hidden = true; refresh(); } } } }, modelOpts);
    const customInp = el("input", { class: "input", placeholder: "model name, e.g. claude-sonnet-5", hidden: !custom, value: custom ? pick.model : "", "aria-label": "Model name",
      on: { input: e => { pick.model = e.target.value.trim(); refresh(); } } });
    const effSel = el("select", { class: "input", "aria-label": "Effort", disabled: a.efforts.length < 2, on: { change: e => { pick.effort = e.target.value; refresh(); } } },
      a.efforts.map(m => el("option", { value: m.id, selected: m.id === pick.effort }, m.label)));
    const acc = el("div", { class: "toggle", role: "switch", tabindex: "0", "aria-checked": String(pick.gameAccess), on: { click: e => { pick.gameAccess = !pick.gameAccess; e.currentTarget.setAttribute("aria-checked", String(pick.gameAccess)); refresh(); },
      keydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.currentTarget.click(); } } } }, el("span", {}, "Let it work in the game’s folder"), el("span", { class: "sw" }));
    const send = el("div", { class: "toggle", role: "switch", tabindex: "0", "aria-checked": String(pick.autoSend), on: { click: e => { pick.autoSend = !pick.autoSend; e.currentTarget.setAttribute("aria-checked", String(pick.autoSend)); },
      keydown: e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); e.currentTarget.click(); } } } }, el("span", {}, "Press Ctrl+V and Enter in the app for me (only if it’s open and in front)"), el("span", { class: "sw" }));
    send.hidden = !a.mode.startsWith("app");
    controls.replaceChildren(el("div", { class: "two-col" }, el("div", { class: "field" }, el("label", {}, "Model"), modelSel, customInp), el("div", { class: "field" }, el("label", {}, "How hard it thinks"), effSel)), acc, send);
    refresh();
  };
  body.append(el("p", { class: "muted" }, "Plunge will open your own agent in a new window and give it the brief. It still asks you before it changes anything."),
    el("div", { class: "box", style: "font-size:14px" }, el("b", {}, "Tip: turn on bypass permissions. "), "Building a VR mod takes many steps, and approving each one gets tedious. In your agent, switch on its own “bypass permissions” (auto-approve) mode before you press Start: in Claude Code press Shift+Tab until it says so, in Codex use its full-auto approval mode. Plunge never turns this on for you. It lets the agent act without asking, so only do it for this task and read what it does."),
    list, controls,
    el("div", { class: "field" }, el("label", {}, "What will run"), preview), notes, otherBox(dlg),
    el("div", { class: "actions" }, btn("dark", "Cancel", null, () => dlg.close()), startBtn));
  draw();
}

/* ---------- add a game that is a program: an emulator with your game file, or any .exe ---------- */
function openAddProgram() {
  const dlg = $("#progDlg"), body = $("#progBody");
  const f = { exe: "", rom: "", name: "", args: "" };
  const field = (label, key, ph, browse, kind) => {
    const inp = el("input", { class: "input", placeholder: ph, "aria-label": label, value: f[key], style: "flex:1", on: { input: e => { f[key] = e.target.value; } } });
    const row = el("div", { style: "display:flex;gap:8px" }, inp, browse ? btn("dark sm", "Browse", null, async () => {
      const r = await api("pick_file", kind); if (r.path) { f[key] = r.path; inp.value = r.path; } }) : null);
    return el("div", { class: "field" }, el("label", {}, label), row);
  };
  const mine = () => S.games.filter(g => g.program);
  const list = el("div", { style: "display:grid;gap:8px" });
  const drawList = () => list.replaceChildren(...mine().map(g => el("div", { class: "prow" }, el("div", {}, el("b", {}, g.name), el("span", { class: "muted", style: "font-size:13px" }, g.emulator ? `Emulator · ${g.emulator}` : "Program")),
    btn("dark sm", "Remove", "trash", async () => { await api("remove_program", g.appid); await refreshGames(false); drawList(); toast("Removed from Plunge. Nothing was deleted."); }))));
  drawList();
  body.replaceChildren(el("h3", {}, "Add a game or emulator"),
    el("p", { class: "muted", style: "font-size:14px" }, "For an emulator, pick the emulator’s program and your own game file. For anything else, pick the program. Plunge never provides game files, and it never touches programs that use anti-cheat."),
    field("Program (.exe)", "exe", "e.g. C:\\Emulators\\Dolphin\\Dolphin.exe", true, "exe"),
    field("Game file (optional)", "rom", "Your own game file, if the program needs one", true, "any"),
    field("Name (optional)", "name", "Shown in your library", false),
    field("Extra start options (optional)", "args", "e.g. --fullscreen", false),
    el("div", { class: "actions" }, btn("dark", "Close", null, () => dlg.close()), btn("blue", "Add to my library", "plus", async () => {
      if (!f.exe.trim()) return toast("Pick the program first", true);
      const r = await api("add_program", f.exe.trim(), f.rom.trim() || null, f.name.trim() || null, f.args.trim());
      await refreshGames(false); toast(`Added ${r.name}${r.emulator ? " (" + r.emulator + ")" : ""}`); drawList();
      f.exe = f.rom = f.name = f.args = ""; $$("input", body).forEach(i => { i.value = ""; });
    })), mine().length ? el("h4", { style: "margin:14px 0 6px" }, "Added by you") : null, list);
  dlg.showModal();
}

/* ---------- headset + "missing a game?" ---------- */
function headsetChips(box, onPick) {
  const h = (S.sys && S.sys.headset) || { choices: [] };
  S.headsetPick = h.type || h.detected || null;
  const draw = () => box.replaceChildren(...h.choices.map(c => el("button", { class: "chip" + (c.id === S.headsetPick ? " on" : ""), role: "radio", "aria-checked": String(c.id === S.headsetPick),
    on: { click: () => { S.headsetPick = c.id; draw(); onPick && onPick(c.id); } } }, c.label)));
  draw();
}
async function openReport() {
  const r = await api("scan_report");
  $("#reportList").replaceChildren(...r.rows.map(x => el("li", {}, el("span", {}, x.label), el("b", {}, x.value))));
  $("#reportNote").textContent = `${r.games} game${r.games === 1 ? "" : "s"} listed right now.`;
  $("#reportDlg").showModal();
}

/* ---------- Search ---------- */
async function renderSearch(text) {
  const t = text.trim().toLowerCase(), body = $("#searchBody"); body.replaceChildren();
  $("#searchTitle").textContent = `Results for “${text.trim()}”`;
  const games = S.games.filter(g => g.name.toLowerCase().includes(t));
  body.append(el("h2", { class: "sec" }, "Games"), games.length ? el("div", { class: "grid" }, games.map(g => gameCard(g))) : el("div", { class: "empty" }, "No games in your library match."));
  let profs = [];
  try { profs = await api("discover_search", text.trim()); } catch (e) { /* hub offline */ }
  if (profs.length) body.append(el("h2", { class: "sec" }, "VR builds"), el("div", { class: "grid" }, profs.map(profileCard)));
}

/* ---------- navigation & data ---------- */
function go(page, appid) {
  if (page === "create") S.createApp = appid === undefined ? S.createApp : appid;
  S.page = page;
  $$(".page").forEach(p => p.classList.toggle("on", p.id === "page-" + page));
  $$(".nav[data-page]").forEach(n => n.classList.toggle("on", n.dataset.page === page));
  $("#main").scrollTop = 0;
  if (page === "discover") loadDiscover();
  if (page === "library") renderLibrary();
  if (page === "create") guard(renderCreate)();
}
async function loadOpenGames() {
  try { S.open = await api("open_games"); if (S.open.error) S.open = null; } catch (e) { S.open = null; }
  if (S.page === "discover" && !dqActive()) renderDiscover();
}
async function loadDiscover() {
  renderDiscover();
  loadOpenGames();
  clearInterval(S.openTimer); S.openTimer = setInterval(() => { if (S.page === "discover" && !document.hidden) loadOpenGames(); }, 20000);
  S.disc = await api("discover");
  try { S.ad = await api("ad"); } catch (e) { S.ad = null; }       // ads must never break Discover
  if (S.page === "discover") renderDiscover();
}
async function refreshGames(redraw = true) {
  const r = await api("games", false); S.games = r.games; S.demo = r.demo;
  if (redraw) { if (S.page === "library") renderLibrary(); if (S.page === "discover") renderDiscover(); }
}
function pollVr() {   // Steam answers arrive in the background: refresh a few times until they're in
  if (S.polls++ > 8 || !S.games.some(g => g.vr && g.vr.via === "checking")) return;
  setTimeout(async () => { await refreshGames(); pollVr(); }, 4000);
}

/* ---------- account: sign in with an email code, no password ---------- */
function paintAccount() {
  const u = S.user;
  $("#avatar").textContent = u ? u.username[0].toUpperCase() : "?";
  $("#accountLabel").textContent = u ? u.username : "Sign in";
}
async function refreshAccount(check) {
  try { S.user = (await api(check ? "account_check" : "account")).user; } catch (e) { /* offline: keep what we have */ }
  paintAccount();
}
function needSignIn(msg) { toast(msg, true); openAccount(); }
function legalLinks() {
  return el("p", { class: "muted", style: "font-size:12.5px;margin:2px 0 0" }, "By continuing you agree to the ",
    el("a", { href: "#", on: { click: e => { e.preventDefault(); guard(() => api("open_legal", "terms"))(); } }, style: "text-decoration:underline" }, "Terms"), " and ",
    el("a", { href: "#", on: { click: e => { e.preventDefault(); guard(() => api("open_legal", "privacy"))(); } }, style: "text-decoration:underline" }, "Privacy Policy"), ".");
}
async function openAccount() {
  const dlg = $("#accountDlg"), body = $("#accountBody");
  if (!dlg.open) dlg.showModal();
  if (S.user) return accountPanel(body, dlg);
  S.auth = S.auth || await api("auth_config");   // Google on or off, password rules
  signInStep(body, dlg, "signin", "");
}
function googleLogo() {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "i"); s.style.width = "20px"; s.style.height = "20px";
  const paths = [["M21.6 12.2c0-.7-.1-1.3-.2-1.9H12v3.7h5.4a4.6 4.6 0 01-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3z", "#4285F4"], ["M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0012 22z", "#34A853"],
    ["M6.4 13.9a6 6 0 010-3.8V7.5H3.1a10 10 0 000 9z", "#FBBC05"], ["M12 6c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 003.1 7.5l3.3 2.6C7.2 7.8 9.4 6 12 6z", "#EA4335"]];
  for (const [d, c] of paths) { const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", d); p.setAttribute("fill", c); s.append(p); }
  return s;
}
function pwRule() { return `Use at least ${(S.auth && S.auth.passwordMin) || 10} characters.`; }

function signInStep(body, dlg, step, email, code, mode) {
  const err = el("div", { class: "err", style: "display:none;line-height:1.4" });
  const fail = e => { err.textContent = e.message; err.style.display = "block"; };
  const clear = () => { err.style.display = "none"; };
  const done = u => { S.user = u; paintAccount(); S.disc = null; dlg.close(); toast(`Signed in as ${u.username}`); };
  const titles = { signin: "Sign in to Plunge", email: mode === "signup" ? "Create your account" : "Sign in with an email code", code: "Check your email", name: "Set up your account", google: "Finish in your browser" };
  body.replaceChildren(el("h3", {}, titles[step]));

  if (step === "signin") {
    const em = el("input", { class: "input", type: "email", placeholder: "Email", autocomplete: "email", spellcheck: "false", "aria-label": "Email address", value: email || "" });
    const pw = el("input", { class: "input", type: "password", placeholder: "Password", autocomplete: "current-password", "aria-label": "Password", style: "margin-top:8px" });
    const go_ = el("button", { class: "btn blue", on: { click: async () => {
      clear(); if (!em.value.trim() || !pw.value) return fail(new Error("Enter your email and password")); go_.disabled = true;
      try { const r = await api("password_sign_in", em.value.trim(), pw.value); done(r.user); } catch (e) { fail(e); go_.disabled = false; } } } }, "Sign in");
    pw.addEventListener("keydown", e => { if (e.key === "Enter") go_.click(); });
    const link = (t, fn) => el("button", { class: "linkbtn", on: { click: fn } }, t);
    body.append(em, pw, err,
      el("div", { class: "linkrow" }, link("Forgot password? Email me a code", () => signInStep(body, dlg, "email", em.value.trim(), null, "code")), link("Create an account", () => signInStep(body, dlg, "email", em.value.trim(), null, "signup"))),
      el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => dlg.close() } }, "Cancel"), go_));
    if (S.auth && S.auth.google) body.append(el("div", { class: "or" }, el("span", {}, "or log in with Google")),
      el("button", { class: "gsi", on: { click: guard(async () => { clear(); await api("google_start"); signInStep(body, dlg, "google"); }) } }, googleLogo(), el("span", {}, "Sign in with Google")));
    body.append(legalLinks());
    setTimeout(() => (em.value ? pw : em).focus(), 30);
  } else if (step === "google") {
    let alive = true;
    body.append(el("p", { class: "muted" }, "A browser window opened so you can sign in with Google. When you finish there, this window signs you in on its own."), el("div", { class: "spin" }), err,
      el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => { alive = false; signInStep(body, dlg, "signin"); } } }, "Cancel")));
    (async () => {
      for (let i = 0; i < 400 && alive && dlg.open; i++) {
        await new Promise(r => setTimeout(r, 1500));
        if (!alive || !dlg.open) return;
        try { const r = await api("google_poll"); if (r.user) { alive = false; return done(r.user); } } catch (e) { alive = false; fail(e); return; }
      }
    })();
  } else if (step === "email") {
    const inp = el("input", { class: "input", type: "email", placeholder: "you@example.com", autocomplete: "email", spellcheck: "false", "aria-label": "Email address", value: email || "" });
    const send = async () => { clear(); const v = inp.value.trim(); if (!v) return fail(new Error("Enter your email address")); send_.disabled = true;
      try { await api("sign_in_start", v); signInStep(body, dlg, "code", v, null, mode); } catch (e) { fail(e); send_.disabled = false; } };
    const send_ = el("button", { class: "btn blue", on: { click: send } }, "Email me a code");
    inp.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
    body.append(el("p", { class: "muted" }, mode === "signup" ? "We email you a 6-digit code to confirm it’s really your address." : "We email you a 6-digit code. It signs you in (or creates your account), and you can set a new password after."),
      inp, err, legalLinks(), el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => signInStep(body, dlg, "signin", inp.value.trim()) } }, "Back"), send_));
    setTimeout(() => inp.focus(), 30);
  } else if (step === "code") {
    const inp = el("input", { class: "input codebox", inputmode: "numeric", maxlength: "6", placeholder: "123456", autocomplete: "one-time-code", "aria-label": "6-digit code" });
    const go_ = async () => { clear(); const c = inp.value.replace(/\D/g, ""); if (c.length !== 6) return fail(new Error("Enter the 6 digits from the email")); go__.disabled = true;
      try { const r = await api("sign_in_verify", email, c, null, null); if (r.needUsername) signInStep(body, dlg, "name", email, c, mode); else { done(r.user); if (!r.user.hasPassword) toast("Signed in. You can set a password from your account.", false); } }
      catch (e) { fail(e); go__.disabled = false; } };
    const go__ = el("button", { class: "btn blue", on: { click: go_ } }, "Continue");
    inp.addEventListener("input", () => { inp.value = inp.value.replace(/\D/g, "").slice(0, 6); if (inp.value.length === 6) go_(); });
    inp.addEventListener("keydown", e => { if (e.key === "Enter") go_(); });
    body.append(el("p", { class: "muted" }, `We sent a code to ${email}. It works for 10 minutes. Check your spam folder if you don’t see it.`), inp, err,
      el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => signInStep(body, dlg, "email", email, null, mode) } }, "Use another email"), go__));
    setTimeout(() => inp.focus(), 30);
  } else {
    const un = el("input", { class: "input", placeholder: "Username", maxlength: "24", autocomplete: "username", spellcheck: "false", "aria-label": "Username" });
    const pw = el("input", { class: "input", type: "password", placeholder: "Password (optional)", autocomplete: "new-password", "aria-label": "Password", style: "margin-top:8px" });
    const mk = async () => { clear(); mk_.disabled = true;
      try { const r = await api("sign_in_verify", email, code, un.value.trim(), pw.value || null); if (r.needUsername) throw new Error("Pick a username"); done(r.user); }
      catch (e) { fail(e); mk_.disabled = false; } };
    const mk_ = el("button", { class: "btn blue", on: { click: mk } }, "Create account");
    un.addEventListener("keydown", e => { if (e.key === "Enter") mk(); }); pw.addEventListener("keydown", e => { if (e.key === "Enter") mk(); });
    body.append(el("p", { class: "muted" }, "Your username is shown on the VR builds you publish: 3 to 24 letters, numbers, - or _. A password is optional; without one you can always sign in with an emailed code."),
      un, pw, el("p", { class: "muted", style: "font-size:12.5px;margin:6px 0 0" }, pwRule()), err, legalLinks(),
      el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => dlg.close() } }, "Cancel"), mk_));
    setTimeout(() => un.focus(), 30);
  }
}
async function accountPanel(body, dlg) {
  const u = S.user;
  body.replaceChildren(el("h3", {}, u.username), el("p", { class: "muted" }, u.email + (u.hasGoogle ? " · Google linked" : "")));
  const list = el("div", { class: "scrolly", style: "max-height:200px" });
  body.append(el("div", { class: "field" }, el("label", { class: "lbl" }, "Your published builds"), list));
  guard(async () => {
    const r = await api("my_builds");
    list.replaceChildren(...(r.profiles.length ? r.profiles.map(p => el("div", { class: "prow" }, el("div", {}, el("b", {}, p.title), el("span", { class: "muted", style: "font-size:13px" }, `${p.downloads} downloads · ${p.likes} likes`)),
      btn("dark sm", "Remove", "trash", async () => { await api("remove_build", p.id); toast("Removed from the hub"); S.disc = null; accountPanel(body, dlg); })))
      : [el("p", { class: "muted", style: "font-size:14px;margin:4px 0" }, "Nothing published yet.")]));
  })();
  const chips = el("div", { class: "chips" },
    el("button", { class: "chip", on: { click: () => settingsForm("name") } }, "Change username"),
    el("button", { class: "chip", on: { click: () => settingsForm("pw") } }, u.hasPassword ? "Change password" : "Set a password"));
  body.append(chips);
  function settingsForm(kind) {
    const err = el("div", { class: "err", style: "display:none" }), fail = e => { err.textContent = e.message; err.style.display = "block"; };
    body.replaceChildren(el("h3", {}, kind === "name" ? "Change username" : (u.hasPassword ? "Change password" : "Set a password")));
    if (kind === "name") {
      const inp = el("input", { class: "input", value: S.user.username, maxlength: "24", "aria-label": "Username", spellcheck: "false" });
      body.append(el("p", { class: "muted" }, "This name is shown on your published builds, and they update to match."), inp, err,
        el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => accountPanel(body, dlg) } }, "Back"),
          el("button", { class: "btn blue", on: { click: async () => { try { const r = await api("rename_account", inp.value.trim()); S.user.username = r.username; paintAccount(); S.disc = null; toast("Username changed"); accountPanel(body, dlg); } catch (e) { fail(e); } } } }, "Save")));
    } else {
      const cur = u.hasPassword ? el("input", { class: "input", type: "password", placeholder: "Current password", autocomplete: "current-password", "aria-label": "Current password" }) : null;
      const nw = el("input", { class: "input", type: "password", placeholder: "New password", autocomplete: "new-password", "aria-label": "New password", style: cur ? "margin-top:8px" : "" });
      body.append(el("p", { class: "muted" }, pwRule()), ...(cur ? [cur] : []), nw, err,
        el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => accountPanel(body, dlg) } }, "Back"),
          el("button", { class: "btn blue", on: { click: async () => { try { await api("set_password", nw.value, cur ? cur.value : null); S.user.hasPassword = true; toast("Password saved"); accountPanel(body, dlg); } catch (e) { fail(e); } } } }, "Save")));
    }
  }
  const del = el("button", { class: "chip", style: "color:#ff8a8a" }, "Delete my account");
  del.addEventListener("click", () => {
    const box = el("input", { class: "input", placeholder: "type: delete my account", autocomplete: "off", spellcheck: "false", "aria-label": "Confirm deletion" });
    const go_ = btn("dark", "Delete everything", "trash", async () => {
      await api("delete_account"); S.user = null; paintAccount(); S.disc = null; dlg.close(); toast("Your account and published builds were deleted");
    });
    go_.disabled = true; box.addEventListener("input", () => { go_.disabled = box.value.trim().toLowerCase() !== "delete my account"; });
    body.replaceChildren(el("h3", {}, "Delete your account?"), el("p", { class: "muted" }, "This removes your account and every build you published to the hub. It can’t be undone."), box,
      el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => accountPanel(body, dlg) } }, "Keep my account"), go_));
  });
  body.append(el("div", { class: "actions", style: "justify-content:space-between" }, del,
    el("span", { style: "display:flex;gap:8px" }, el("button", { class: "btn dark", on: { click: () => dlg.close() } }, "Close"),
      btn("blue", "Sign out", null, async () => { await api("sign_out"); S.user = null; paintAccount(); S.disc = null; dlg.close(); toast("Signed out"); }))));
}

/* ---------- publish a build to the hub (the marketplace) ---------- */
async function openPublish() {
  const dlg = $("#publishDlg"), body = $("#publishBody");
  if (!dlg.open) dlg.showModal();
  body.replaceChildren(el("h3", {}, "Publish a build"), el("p", { class: "muted" }, "Loading your builds…"));
  let data;
  try { data = await api("local_builds"); } catch (e) { return body.replaceChildren(el("h3", {}, "Publish a build"), el("div", { class: "err", style: "display:block" }, e.message), el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => dlg.close() } }, "Close"))); }
  const signed = el("div", {});
  const paintSigned = () => {
    signed.replaceChildren(S.user
      ? el("p", { class: "muted", style: "font-size:14px;margin:0 0 6px" }, `Publishing as ${S.user.username}. Your name is shown on the build.`)
      : el("div", { class: "box", style: "display:flex;align-items:center;justify-content:space-between;gap:10px" }, el("span", {}, "You need to sign in to publish."),
          el("button", { class: "btn blue", on: { click: () => { dlg.close(); openAccount(); } } }, "Sign in")));
  };
  paintSigned();
  const list = el("div", { class: "scrolly", style: "max-height:340px;display:grid;gap:8px" });
  if (!data.profiles.length) list.append(el("p", { class: "muted" }, "You don’t have a finished VR build yet. Go to Create, pick a game and press “Send to my AI agent”. When your agent saves the build, it shows up here."));
  data.profiles.forEach(p => {
    const msg = el("div", { class: p.ready ? "muted" : "err", style: "font-size:13px;display:" + (p.ready ? "none" : "block") }, p.errors.join(" · "));
    const pub = el("button", { class: "btn blue sm" }, icon("up"), "Publish");
    pub.disabled = !p.ready;
    pub.addEventListener("click", async () => {
      if (!S.user) { toast("Sign in first", true); dlg.close(); return openAccount(); }
      pub.disabled = true; msg.style.display = "block"; msg.className = "muted"; msg.textContent = "Uploading… this can take a minute for a big build.";
      try { await api("publish", p.slug); msg.className = "muted"; msg.style.color = "#59d98e"; msg.textContent = "Published! It’s in Discover now."; S.disc = null; toast("Published to the hub"); loadDiscover(); }
      catch (e) { msg.className = "err"; msg.style.color = ""; msg.textContent = e.message; pub.disabled = false; }
    });
    list.append(el("div", { class: "prow", style: "flex-wrap:wrap" }, el("div", { style: "flex:1;min-width:200px" }, el("b", {}, p.title),
      el("span", { class: "muted", style: "font-size:13px" }, `${TIER[p.tier] || p.tier || "VR build"} · ${p.mb} MB${p.ready ? "" : " · can’t be published yet"}`)), pub, msg));
  });
  if (data.incomplete.length) list.append(el("div", { class: "box" }, el("b", {}, "Unfinished builds"),
    el("p", { class: "muted", style: "font-size:13px;margin:4px 0 0" }, `These folders have no build file yet, so there’s nothing to publish: ${data.incomplete.join(", ")}. Your AI agent didn’t finish saving them. Open the game in Create and send the brief again.`)));
  body.replaceChildren(el("h3", {}, "Publish a build"), el("p", { class: "muted" }, "Share a VR build you made so other players can find it in Discover. Builds can’t contain a game’s own files."), signed, list,
    el("div", { class: "actions" }, el("button", { class: "btn dark", on: { click: () => dlg.close() } }, "Close")));
}
async function boot() {
  const [g, sys] = await Promise.all([api("games", false), api("system")]);
  S.games = g.games; S.demo = g.demo; S.sys = sys;
  refreshAccount(false).then(() => refreshAccount(true));
  $("#accountOpen").addEventListener("click", openAccount);
  $("#publishOpen").addEventListener("click", guard(openPublish));
  $$(".nav[data-page]").forEach(n => n.addEventListener("click", () => go(n.dataset.page, n.dataset.page === "create" ? null : undefined)));
  $("#railToggle").addEventListener("click", () => $("#rail").classList.toggle("open"));
  $$("#libFilters .chip[data-f]").forEach(c => c.addEventListener("click", () => { S.libFilter = c.dataset.f; renderLibrary(); }));
  $("#missingBtn").addEventListener("click", guard(openReport));
  $("#reportClose").addEventListener("click", () => $("#reportDlg").close());
  $("#reportAdd").addEventListener("click", () => $("#addFolder").click());
  $("#addProgram").addEventListener("click", openAddProgram);
  const runDeep = (btnId, depth, seconds, label) => guard(async () => {
    const b = $(btnId); b.disabled = true; $("#reportNote").textContent = `Scanning your drives (${label})…`;
    try {
      const r = await api("deep_scan", seconds, depth);
      await refreshGames(); await openReport();
      $("#reportNote").textContent = `Finished in ${r.seconds}s${r.timedOut ? " (stopped at the time limit; run it again to continue)" : ""}: ${r.newGames} new game${r.newGames === 1 ? "" : "s"} found.`;
    } finally { b.disabled = false; }
  });
  $("#reportDeep").addEventListener("click", runDeep("#reportDeep", 4, 150, "a few seconds"));
  $("#reportDeeper").addEventListener("click", runDeep("#reportDeeper", 6, 240, "this can take a minute or two"));
  $("#addFolder").addEventListener("click", guard(async () => {
    const r = await api("pick_game_folder");
    if (r.cancelled) return;
    toast(r.found > 0 ? `Added. Found ${r.found} new game${r.found === 1 ? "" : "s"}.` : "Added, but no new games were found in it.");
    await refreshGames();
  }));
  const search = $("#search");
  search.addEventListener("keydown", guard(async e => { if (e.key === "Enter" && search.value.trim()) { go("search"); await renderSearch(search.value); } }));
  document.addEventListener("keydown", e => { if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); search.focus(); } });
  $("#joinOpen").addEventListener("click", () => $("#joinDlg").showModal());
  $("#joinCancel").addEventListener("click", () => $("#joinDlg").close());
  $("#joinGo").addEventListener("click", guard(async () => { const c = $("#joinCode").value.trim(); if (!c) return toast("Paste a join code first", true); await joinCode(c); $("#joinDlg").close(); }));
  $("#promptClose").addEventListener("click", () => $("#promptDlg").close());
  $("#promptCopy").addEventListener("click", guard(async () => { await api("copy_text", $("#promptText").value); toast("Brief copied"); $("#promptDlg").close(); }));
  $("#settingsOpen").addEventListener("click", () => {
    $("#linkToggle").setAttribute("aria-checked", String(!!(S.sys.links && S.sys.links.registered)));
    const hs = S.sys.headset || { choices: [] }, sel = $("#headsetSel");
    sel.replaceChildren(el("option", { value: "" }, hs.detected ? `Not chosen (looks like: ${hs.choices.find(c => c.id === hs.detected).label})` : "Not chosen"),
      ...hs.choices.map(c => el("option", { value: c.id, selected: c.id === hs.type }, c.label)));
    $("#legalLinks").replaceChildren(...[["terms", "Terms"], ["privacy", "Privacy"], ["copyright", "Copyright"], ["guidelines", "Guidelines"], ["notices", "Notices"]]
      .map(([k, l]) => el("button", { class: "chip", on: { click: guard(() => api("open_legal", k)) } }, l)));
    const f = [["Version", S.sys.version || "?"], ["Steam", S.demo ? "not found (demo library)" : "found"], ["VR runtime", S.sys.headsetReady ? "ready" : "not found"], ["UEVR", S.sys.uevrInstalled ? "installed" : "not installed"],
      ["Hub", S.sys.hub], ["Lobby service", S.sys.lobby]];
    $("#settingsFacts").replaceChildren(...f.map(([k, v]) => el("li", {}, el("span", {}, k), el("b", {}, v))));
    guard(async () => {
      const a = S.ad || await api("ad"), t = $("#adToggle");
      t.setAttribute("aria-checked", String(a.enabled));
      $("#adNote").textContent = a.configured
        ? `Sponsored cards come from ${a.host}. Loading one shares your IP address with that provider. Plunge sends them nothing about your games.`
        : "No ad source is set up, so no sponsored cards are shown.";
    })();
    $("#settingsDlg").showModal();
  });
  $("#headsetSel").addEventListener("change", guard(async e => {
    if (!e.target.value) return;
    S.sys.headset = await api("set_headset", e.target.value); toast("Saved: " + S.sys.headset.label);
  }));
  $("#linkToggle").addEventListener("click", guard(async e => {
    const t = e.currentTarget, on = t.getAttribute("aria-checked") !== "true";
    S.sys.links = await api("register_links", on); t.setAttribute("aria-checked", String(!!S.sys.links.registered));
    toast(on ? "plunge:// links will open Plunge" : "plunge:// links turned off");
  }));
  $("#adToggle").addEventListener("click", guard(async e => {
    const t = e.currentTarget;           // currentTarget is cleared after the first await, so keep our own reference
    const on = t.getAttribute("aria-checked") !== "true";
    await api("ads_enable", on); t.setAttribute("aria-checked", String(on)); S.ad = null; toast(on ? "Sponsored cards on" : "Sponsored cards off");
  }));
  $("#settingsClose").addEventListener("click", () => $("#settingsDlg").close());
  $$("dialog").forEach(d => d.addEventListener("click", e => { if (e.target === d) d.close(); }));
  go("discover"); pollVr();

  // a plunge://join/CODE link opened the app: never join automatically, let the player confirm
  const link = await api("startup_link");
  if (link.code) { $("#joinCode").value = link.code; $("#joinDlg").showModal(); toast("Join link received. Press Join to enter the game."); }
  // a second Plunge started with a join link hands it to this one: keep checking, and always ask before joining
  setInterval(async () => {
    try { const l = await api("startup_link"); if (l.code && !$("#joinDlg").open) { $("#joinCode").value = l.code; $("#joinDlg").showModal(); toast("Join link received. Press Join to enter the game."); } } catch (e) { /* ignore */ }
  }, 3000);
  // update notice (only when an update address is configured)
  api("update_check").then(u => {
    if (u.available) {
      const bar = el("div", { class: "empty", style: "margin:14px 0;grid-auto-flow:column;align-items:center;justify-content:space-between;text-align:left" },
        el("span", {}, `Plunge ${u.version} is available. ${u.notes || ""}`), btn("blue sm", "Download", "up", () => api("open_update")));
      $("#page-discover").prepend(bar);
    }
  }).catch(() => {});
  $("#logsBtn").addEventListener("click", guard(() => api("open_logs")));
  $("#updateBtn").addEventListener("click", guard(async () => {
    const u = await api("update_check");
    toast(!u.enabled ? "No update address is set up." : u.available ? `Version ${u.version} is available.` : u.error ? u.error : "You have the latest version.", !!u.error);
  }));
  // first run
  headsetChips($("#headsetChips"));
  $("#welcomeGo").addEventListener("click", guard(async () => {
    if (S.headsetPick) S.sys.headset = await api("set_headset", S.headsetPick);
    await api("onboarded", true); $("#welcomeDlg").close();
  }));
  if (!link.code && !(await api("onboarded", null)).done) $("#welcomeDlg").showModal();
}
window.addEventListener("pywebviewready", () => boot().catch(e => toast(e.message, true)));
