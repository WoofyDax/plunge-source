// plungevr.com/account: sign in (password, emailed code, or Google), manage your username and password, see and remove your published builds.
// The hub keeps the session in an HttpOnly cookie, so nothing secret is ever visible to this script.
const HUB = "https://hub.plungevr.com";
const root = document.querySelector("[data-account]");
let CONFIG = { google: false, passwordMin: 10 };

async function call(path, body) {
  let r;
  try {
    r = await fetch(HUB + path, {
      method: body === undefined ? "GET" : "POST", credentials: "include",
      headers: { "X-Plunge-Client": "web", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Can't reach Plunge right now. Check your connection and try again.");
  }
  let data = null;
  try { data = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) { const err = new Error((data && data.error) || "Something went wrong"); err.status = r.status; throw err; }
  return data;
}

const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v); }
  kids.flat().forEach((k) => k != null && e.append(k));
  return e;
};

function show(...nodes) { root.replaceChildren(...nodes); }
const heading = (t) => h("h1", {}, t);
const note = (t) => h("p", { class: "muted" }, t);
function errBox() { const e = h("div", { class: "err", role: "alert", hidden: true }); e.fail = (m) => { e.textContent = m; e.hidden = false; }; e.clear = () => { e.hidden = true; }; return e; }
function button(label, cls, fn) { const b = h("button", { type: "button", class: "abtn " + cls }); b.textContent = label; b.addEventListener("click", async () => { b.disabled = true; try { await fn(); } finally { b.disabled = false; } }); return b; }
const linkBtn = (label, fn) => { const b = h("button", { type: "button", class: "alink" }); b.textContent = label; b.addEventListener("click", fn); return b; };
const legal = () => h("p", { class: "tiny" }, "By continuing you agree to the ", h("a", { href: "/terms" }, "Terms"), " and ", h("a", { href: "/privacy" }, "Privacy Policy"), ".");
const pwRule = () => "Use at least " + CONFIG.passwordMin + " characters.";

function googleG() {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", "18"); s.setAttribute("height", "18"); s.setAttribute("aria-hidden", "true");
  for (const [d, c] of [["M21.6 12.2c0-.7-.1-1.3-.2-1.9H12v3.7h5.4a4.6 4.6 0 01-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3z", "#4285F4"], ["M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0012 22z", "#34A853"],
    ["M6.4 13.9a6 6 0 010-3.8V7.5H3.1a10 10 0 000 9z", "#FBBC05"], ["M12 6c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 003.1 7.5l3.3 2.6C7.2 7.8 9.4 6 12 6z", "#EA4335"]]) {
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", d); p.setAttribute("fill", c); s.append(p);
  }
  return s;
}

// the standard "Sign in with Google" button: white, the four-colour G, Google's wording
function googleButton() {
  const b = h("button", { type: "button", class: "gsi" }, googleG(), h("span", {}, "Sign in with Google"));
  b.addEventListener("click", () => { location.href = HUB + "/auth/google/start?mode=web"; });
  return b;
}
// ---- sign in ----
function signIn(prefill = "") {
  const err = errBox();
  const em = h("input", { class: "ainput", type: "email", placeholder: "Email", autocomplete: "email", "aria-label": "Email address", value: prefill });
  const pw = h("input", { class: "ainput", type: "password", placeholder: "Password", autocomplete: "current-password", "aria-label": "Password" });
  const go = button("Sign in", "blue", async () => {
    err.clear();
    if (!em.value.trim() || !pw.value) return err.fail("Enter your email and password");
    try { await call("/auth/login", { email: em.value.trim(), password: pw.value }); account(); } catch (e) { err.fail(e.message); }
  });
  pw.addEventListener("keydown", (e) => { if (e.key === "Enter") go.click(); });
  show(heading("Sign in to Plunge"), em, pw, err,
    h("div", { class: "linkrow" }, linkBtn("Forgot password? Email me a code", () => emailStep(em.value.trim(), "code")), linkBtn("Create an account", () => emailStep(em.value.trim(), "signup"))), go,
    CONFIG.google ? h("div", { class: "or" }, h("span", {}, "or log in with Google")) : null, CONFIG.google ? googleButton() : null, legal());
  (em.value ? pw : em).focus();
}

function emailStep(prefill, mode) {
  const err = errBox();
  const inp = h("input", { class: "ainput", type: "email", placeholder: "you@example.com", autocomplete: "email", "aria-label": "Email address", value: prefill || "" });
  const send = button("Email me a code", "blue", async () => {
    err.clear();
    if (!inp.value.trim()) return err.fail("Enter your email address");
    try { await call("/auth/start", { email: inp.value.trim() }); codeStep(inp.value.trim(), mode); } catch (e) { err.fail(e.message); }
  });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") send.click(); });
  show(heading(mode === "signup" ? "Create your account" : "Sign in with an email code"),
    note(mode === "signup" ? "We email you a 6-digit code to confirm it's really your address." : "We email you a 6-digit code. It signs you in (or creates your account), and you can set a new password after."),
    inp, err, legal(), send, button("Back", "dark", async () => signIn(inp.value.trim())));
  inp.focus();
}

function codeStep(email, mode) {
  const err = errBox();
  const inp = h("input", { class: "ainput code", inputmode: "numeric", maxlength: "6", placeholder: "123456", autocomplete: "one-time-code", "aria-label": "6-digit code" });
  const go = button("Continue", "blue", async () => {
    err.clear();
    const c = inp.value.replace(/\D/g, "");
    if (c.length !== 6) return err.fail("Enter the 6 digits from the email");
    try {
      const r = await call("/auth/verify", { email, code: c });
      if (r.needUsername) return details(email, c);
      account();
    } catch (e) { err.fail(e.message); }
  });
  inp.addEventListener("input", () => { inp.value = inp.value.replace(/\D/g, "").slice(0, 6); if (inp.value.length === 6) go.click(); });
  show(heading("Check your email"), note("We sent a code to " + email + ". It works for 10 minutes. Check your spam folder if you don't see it."), inp, err, go,
    button("Use another email", "dark", async () => emailStep(email, mode)));
  inp.focus();
}

function details(email, code) {
  const err = errBox();
  const un = h("input", { class: "ainput", placeholder: "Username", maxlength: "24", autocomplete: "username", "aria-label": "Username" });
  const pw = h("input", { class: "ainput", type: "password", placeholder: "Password (optional)", autocomplete: "new-password", "aria-label": "Password" });
  const go = button("Create account", "blue", async () => {
    err.clear();
    try { await call("/auth/verify", { email, code, username: un.value.trim(), password: pw.value || null }); account(); } catch (e) { err.fail(e.message); }
  });
  show(heading("Set up your account"), note("Your username is shown on the VR builds you publish: 3 to 24 letters, numbers, - or _. A password is optional; without one you can always sign in with an emailed code."),
    un, pw, h("p", { class: "tiny" }, pwRule()), err, go);
  un.focus();
}

// ---- signed in ----
async function account() {
  let me;
  try { me = (await call("/me")).user; } catch (e) {
    if (e.status === 401) return signIn();
    return show(heading("Account"), h("div", { class: "err" }, e.message));
  }
  const list = h("div", { class: "list" });
  const refresh = async () => {
    try {
      const rows = (await call("/me/profiles")).profiles;
      list.replaceChildren(...(rows.length ? rows.map((p) => h("div", { class: "row" },
        h("div", {}, h("b", {}, p.title), h("span", { class: "muted" }, p.downloads + " downloads · " + p.likes + " likes")),
        button("Remove", "dark", async () => { await call("/profiles/" + encodeURIComponent(p.id) + "/remove", {}); refresh(); })))
        : [h("p", { class: "muted" }, "Nothing published yet. Publish a VR build from the Plunge app.")]));
    } catch (e) { list.replaceChildren(h("div", { class: "err" }, e.message)); }
  };
  refresh();
  show(heading(me.username), note(me.email + (me.hasGoogle ? " · Google linked" : "")), h("h2", {}, "Your published builds"), list,
    h("div", { class: "actions" },
      button("Change username", "dark", async () => changeName(me)),
      button(me.hasPassword ? "Change password" : "Set a password", "dark", async () => changePassword(me))),
    h("div", { class: "actions" },
      button("Sign out", "blue", async () => { try { await call("/auth/logout", {}); } catch (e) { /* ignore */ } signIn(); }),
      button("Delete my account", "danger", async () => deleteAccount())));
}

function changeName(me) {
  const err = errBox();
  const inp = h("input", { class: "ainput", value: me.username, maxlength: "24", "aria-label": "Username" });
  show(heading("Change username"), note("This name is shown on your published builds, and they update to match."), inp, err,
    button("Save", "blue", async () => { err.clear(); try { await call("/me/username", { username: inp.value.trim() }); account(); } catch (e) { err.fail(e.message); } }),
    button("Back", "dark", async () => account()));
  inp.focus();
}

function changePassword(me) {
  const err = errBox();
  const cur = me.hasPassword ? h("input", { class: "ainput", type: "password", placeholder: "Current password", autocomplete: "current-password", "aria-label": "Current password" }) : null;
  const nw = h("input", { class: "ainput", type: "password", placeholder: "New password", autocomplete: "new-password", "aria-label": "New password" });
  show(heading(me.hasPassword ? "Change password" : "Set a password"), note(pwRule()), cur, nw, err,
    button("Save", "blue", async () => { err.clear(); try { await call("/me/password", { new: nw.value, current: cur ? cur.value : null }); account(); } catch (e) { err.fail(e.message); } }),
    button("Back", "dark", async () => account()));
  (cur || nw).focus();
}

function deleteAccount() {
  const err = errBox();
  const inp = h("input", { class: "ainput", placeholder: "type: delete my account", autocomplete: "off", "aria-label": "Confirm deletion" });
  const go = button("Delete everything", "danger", async () => {
    err.clear();
    if (inp.value.trim().toLowerCase() !== "delete my account") return err.fail('Type "delete my account" to confirm');
    try { await call("/me/delete", { confirm: "delete my account" }); signIn(); } catch (e) { err.fail(e.message); }
  });
  show(heading("Delete your account?"), note("This removes your account and every build you published. It can't be undone."), inp, err, go, button("Keep my account", "dark", async () => account()));
  inp.focus();
}

async function start() {
  try { CONFIG = { ...CONFIG, ...(await call("/auth/config")) }; } catch (e) { /* keep defaults */ }
  account();
}
if (root) start();
