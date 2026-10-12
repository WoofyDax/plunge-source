// Turns the "Sign in" button in the top bar into your username when you are signed in. If anything fails it stays "Sign in".
const link = document.querySelector("[data-signin]");
if (link) {
  fetch("https://hub.plungevr.com/me", { credentials: "include", headers: { "X-Plunge-Client": "web" } })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d && d.user && d.user.username) link.textContent = d.user.username; })
    .catch(() => {});
}
