(function () {
  var m = location.pathname.match(/^\/join\/([A-Za-z0-9]{4,12})\/?$/);
  var code = m ? m[1].toUpperCase() : "";
  var ok = /^[A-Z2-9]{4,12}$/.test(code);
  var codeEl = document.getElementById("jcode"), open = document.getElementById("jopen"), msg = document.getElementById("jmsg");
  if (!ok) { msg.textContent = "That invite link doesn\u2019t look right. Ask your friend to send it again."; open.hidden = true; return; }
  codeEl.textContent = code;
  open.href = "plunge://join/" + code;
  setTimeout(function () { try { location.href = "plunge://join/" + code; } catch (e) {} }, 400);
})();
