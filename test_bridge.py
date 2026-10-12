"""Calls the same Bridge the window uses, and runs the commands the brief tells an agent to run."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import app  # noqa: E402

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


from core import recipe  # noqa: E402

LAUNCHED = []
recipe.launch = lambda *a, **k: LAUNCHED.append(a) or {"mode": "stubbed"}  # tests must never start a real game

b = app.Bridge()
g = b.games(False)
check("bridge: games", len(g["games"]) > 0 and "demo" in g)
acc = next((x for x in g["games"] if x["status"] == "supported"), None)
check("bridge: games carry VR info", all("vr" in x and "customized" in x for x in g["games"]))
check("bridge: unknown game becomes {error}", "error" in b.game_info("nope"))
check("bridge: blocked game cannot play",
      "anti-cheat" in b.play(next(x for x in g["games"] if x["status"] == "blocked")["appid"], None, "solo", None, None).get("error", "").lower())
no_vr = next((x for x in g["games"] if x["status"] == "experimental" and not x["vr"]["level"]), None)
if no_vr:
    check("bridge: non-VR AI-build game without a profile cannot play",
          "profile" in b.play(no_vr["appid"], None, "solo", None, None).get("error", "").lower())
vr_game = next((x for x in g["games"] if x["vr"]["level"] and x["status"] != "blocked" and x["engine"] != "unreal"), None)
if vr_game:
    r = b.play(vr_game["appid"], None, "solo", None, None)
    check("bridge: built-in VR game plays without a profile", "error" not in r and "built-in VR" in " ".join(r["steps"]))
check("bridge: nothing real was launched", len(LAUNCHED) <= 1)
check("bridge: host without a profile fails cleanly", "error" in b.host(acc["appid"], "no-such-profile", False, None))
check("bridge: join with a bad code fails cleanly", "error" in b.join("ZZZZZZ"))

p = b.prompt(acc["appid"])["prompt"]
check("brief names the game", acc["name"] in p)
check("brief has no unfilled placeholders", not re.search(r"\{[a-z_-]+\}", p.replace("{game}", "").replace("{uevr-config}", "").replace("{address}", "").replace("{port}", "")))
check("brief has no Melty token or URL", "llc_" not in p and "melty.gg" not in p)
check("brief tells the agent to use universal-modder", "universal-modder" in p)
check("brief forbids official servers", "official servers" in p)

# run the exact commands the brief gives the agent
cmds = re.findall(r"^  (\".+? tool (?:game_info|search_profiles) \d+)$", p, re.M)
check("brief lists agent commands", len(cmds) == 2)
for c in cmds:
    out = subprocess.run(c, shell=True, capture_output=True, text=True)
    check("agent command works: " + c.split(" tool ")[1], out.returncode == 0 and json.loads(out.stdout) is not None)

# clipboard round trip with unicode (caller restores the user's clipboard)
text = "Plunge test ✓ — é 日本"
check("clipboard copy", b.copy_text(text).get("ok") is True)
got = subprocess.run(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                     capture_output=True, text=True, encoding="utf-8").stdout.strip()
check("clipboard holds the exact unicode text", got == text)

print("\n%d failed" % len(fails) if fails else "\nall passed")
sys.exit(1 if fails else 0)
