"""Find AI coding agents on this PC and start one on a Plunge brief.

Plunge does not talk to any AI service itself. It opens the player's OWN agent (Claude Code, Codex, Gemini CLI...) in a
visible terminal window, in a folder that holds BRIEF.md, with a one-line first message that tells it to read that file.
The player stays in control: the agent's own permission prompts apply, and Plunge never passes a flag that turns them off.

Flags below come from each tool's own documentation (Claude Code CLI reference, Codex CLI reference, Gemini CLI reference).
A tool whose "start with a message" flag could not be confirmed (Grok, others) is "paste" mode: Plunge opens it in the folder
and puts the one-line message on the clipboard.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from . import paths

MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
FIRST_MESSAGE = "Read BRIEF.md in the current folder and follow it exactly. It is my request for a Plunge VR build."
# flags that would turn off the agent's own safety prompts: Plunge never passes these
FORBIDDEN_FLAGS = ("dangerously", "yolo", "danger-full-access", "bypass", "skip-permissions", "approval-mode", "--sandbox", "-s ", "--ask-for-approval")
CMD_UNSAFE = re.compile(r'[&|<>^%!"\r\n]')

DEFAULT_ONLY = [("default", "Your default")]
PROVIDERS = {
    "claude": {"name": "Claude Code", "exes": ["claude"], "mode": "auto",
               "models": [("default", "Your default"), ("sonnet", "Sonnet"), ("opus", "Opus"), ("haiku", "Haiku")],
               "efforts": [("default", "Default"), ("low", "Low"), ("medium", "Medium"), ("high", "High"), ("xhigh", "Extra high"), ("max", "Max")],
               "install": "https://code.claude.com/docs/en/quickstart", "plans": "https://claude.com/pricing"},
    "codex": {"name": "Codex", "exes": ["codex"], "mode": "auto", "models": DEFAULT_ONLY,
              "efforts": [("default", "Default"), ("low", "Low"), ("medium", "Medium"), ("high", "High")],
              "install": "https://developers.openai.com/codex/cli", "plans": "https://openai.com/chatgpt/pricing"},
    # desktop apps: opened through the app's own link (Claude) or by starting the app (Codex/ChatGPT has no link for a message)
    "claude-app": {"name": "Claude desktop app", "exes": [], "mode": "app", "models": DEFAULT_ONLY, "efforts": [("default", "Uses the app’s setting")],
                   "install": "https://claude.com/download", "plans": "https://claude.com/pricing"},
    "codex-app": {"name": "ChatGPT / Codex desktop app", "exes": [], "mode": "app-paste", "models": DEFAULT_ONLY, "efforts": [("default", "Uses the app’s setting")],
                  "install": "https://openai.com/codex", "plans": "https://openai.com/chatgpt/pricing"},
    # editors with built-in AI agents: Plunge opens the folder, the message goes on the clipboard for the editor's chat
    "cursor-ide": {"name": "Cursor", "exes": ["cursor"], "mode": "editor", "models": DEFAULT_ONLY, "efforts": [("default", "Uses the editor’s setting")],
                   "install": "https://cursor.com", "plans": "https://cursor.com/pricing"},
    "windsurf": {"name": "Windsurf", "exes": ["windsurf"], "mode": "editor", "models": DEFAULT_ONLY, "efforts": [("default", "Uses the editor’s setting")],
                 "install": "https://windsurf.com", "plans": "https://windsurf.com/pricing"},
    "vscode": {"name": "VS Code (Copilot or any AI extension)", "exes": ["code"], "mode": "editor", "models": DEFAULT_ONLY,
               "efforts": [("default", "Uses the editor’s setting")],
               "install": "https://code.visualstudio.com", "plans": "https://github.com/features/copilot/plans"},
    "gemini": {"name": "Gemini CLI", "exes": ["gemini"], "mode": "auto",
               "models": [("default", "Your default"), ("auto", "Auto"), ("pro", "Pro"), ("flash", "Flash"), ("flash-lite", "Flash-Lite")],
               "efforts": [("default", "Default")],
               "install": "https://github.com/google-gemini/gemini-cli", "plans": "https://one.google.com/about/google-ai-plans/"},
    "grok": {"name": "Grok Build", "exes": ["grok"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
             "install": "https://docs.x.ai/build/overview", "plans": "https://grok.com"},
    "opencode": {"name": "OpenCode", "exes": ["opencode"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
                 "install": "https://opencode.ai", "plans": "https://opencode.ai"},
    "aider": {"name": "Aider", "exes": ["aider"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
              "install": "https://aider.chat", "plans": "https://aider.chat"},
    "cursor": {"name": "Cursor Agent", "exes": ["cursor-agent"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
               "install": "https://cursor.com/cli", "plans": "https://cursor.com/pricing"},
    "copilot": {"name": "GitHub Copilot CLI", "exes": ["copilot"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
                "install": "https://github.com/features/copilot/cli", "plans": "https://github.com/features/copilot/plans"},
    "qwen": {"name": "Qwen Code", "exes": ["qwen"], "mode": "paste", "models": DEFAULT_ONLY, "efforts": [("default", "Default")],
             "install": "https://github.com/QwenLM/qwen-code", "plans": "https://github.com/QwenLM/qwen-code"},
}


class AgentError(ValueError):
    pass


def _extra_dirs():
    home = Path.home()
    return [os.path.join(os.environ.get("APPDATA", ""), "npm"), str(home / ".local" / "bin"), str(home / ".claude" / "local"),
            str(home / ".bun" / "bin"), str(home / "scoop" / "shims"), str(home / ".cargo" / "bin"), str(home / ".grok" / "bin")]


def find_exe(names):
    """Path of the first of `names` found on PATH or in the usual per-user install folders."""
    for n in names:
        hit = shutil.which(n)
        if hit:
            return hit
    for d in _extra_dirs():
        for n in names:
            for ext in (".exe", ".cmd", ".bat"):
                p = Path(d) / (n + ext)
                if p.is_file():
                    return str(p)
    return None


def _vkey(text):
    """'2.1.295' -> (2, 1, 295), so the newest copy sorts last."""
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-_]", str(text)))


def _appx_exe(prefix, rel):
    """Where a Microsoft Store app keeps a file, read from the package registry (Windows doesn't allow listing its WindowsApps folder)."""
    if not winreg:
        return None
    key = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    best = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                name = winreg.EnumKey(k, i)
                if name.startswith(prefix) and "_x64_" in name:
                    with winreg.OpenKey(k, name) as pk:
                        root = winreg.QueryValueEx(pk, "PackageRootFolder")[0]
                    exe = Path(root).joinpath(*rel)
                    if exe.is_file() and (best is None or _vkey(name) > _vkey(best[0])):
                        best = (name, str(exe))
    except OSError:
        return None
    return best[1] if best else None


def bundled(pid):
    """Agents that ship inside a desktop app instead of being on PATH. Returns (path, where) or (None, None)."""
    if pid == "claude":                                  # the Claude desktop app downloads its own Claude Code
        base = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
        best = None
        for exe in (base.glob("*/*/claude.exe") if base.is_dir() else []):
            if best is None or _vkey(exe.parent.parent.name) > _vkey(best.parent.parent.name):
                best = exe
        return (str(best), "Claude desktop app") if best else (None, None)
    if pid == "codex":                                   # the Codex desktop app carries codex.exe
        exe = _appx_exe("OpenAI.Codex_", ("app", "resources", "codex.exe"))
        return (exe, "Codex desktop app") if exe else (None, None)
    return (None, None)


def _appx_family(prefix):
    """Package family name of an installed Store app ('OpenAI.Codex_2p2nqsd0c76g0'), from the package registry."""
    if not winreg:
        return None
    key = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                name = winreg.EnumKey(k, i)
                if name.startswith(prefix) and "__" in name:
                    return name.split("_")[0] + "_" + name.split("__")[1]
    except OSError:
        pass
    return None


def app_target(pid):
    """For a desktop app: what to start it with, or None if it isn't installed."""
    if pid == "claude-app":                               # the app registers the claude:// link; it must point at a real file
        if not winreg:
            return None
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"claude\shell\open\command") as k:
                cmd = winreg.QueryValueEx(k, "")[0]
        except OSError:
            return None
        m = re.match(r'\s*"([^"]+)"', cmd)
        return m.group(1) if m and Path(m.group(1)).is_file() else None
    if pid == "codex-app":
        fam = _appx_family("OpenAI.Codex_")
        return "shell:AppsFolder\\%s!App" % fam if fam else None
    return None


def find_provider(pid):
    """(path, where it was found) for an agent: PATH, the usual per-user folders, then desktop-app copies."""
    p = PROVIDERS[pid]
    if p["mode"].startswith("app"):
        t = app_target(pid)
        return (t, "this PC") if t else (None, None)
    path = find_exe(p["exes"])
    if path:
        return path, "this PC"
    return bundled(pid)


def _version(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL)
        line = (out.stdout or out.stderr or "").strip().splitlines()
        return (line[0] if line else "")[:60] if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect(with_versions=True):
    """Every known agent, with where it was found (or None)."""
    out = []
    for pid, p in PROVIDERS.items():
        path, where = find_provider(pid)
        out.append({"id": pid, "name": p["name"], "found": bool(path), "path": path, "where": where, "mode": p["mode"],
                    "version": _version(path) if path and with_versions and not p["mode"].startswith("app") else "",
                    "models": [{"id": i, "label": l} for i, l in p["models"]], "efforts": [{"id": i, "label": l} for i, l in p["efforts"]],
                    "install": p["install"], "plans": p["plans"]})
    return out


def check_choice(provider, model, effort):
    if provider not in PROVIDERS:
        raise AgentError("unknown agent: %s" % provider)
    p = PROVIDERS[provider]
    model = model or "default"
    if model != "default" and not MODEL_RE.fullmatch(model):
        raise AgentError("that model name has characters that aren't allowed")
    effort = effort or "default"
    if effort not in [e for e, _ in p["efforts"]]:
        raise AgentError("%s doesn't have a '%s' effort setting" % (p["name"], effort))
    return model, effort


def _assert_safe(args):
    """Last line of defence: no FLAG may look like one that disables the agent's safety prompts."""
    for a in args[1:]:
        low = str(a).lower()
        if str(a).startswith("-") and any(f in low for f in FORBIDDEN_FLAGS):
            raise AgentError("refusing to pass a flag that disables the agent's safety prompts: %s" % a)


def build_command(provider, exe, model="default", effort="default", add_dirs=(), workdir=None):
    """The exact argument list (no shell). Returns (args, notes)."""
    model, effort = check_choice(provider, model, effort)
    notes = []
    batch = str(exe).lower().endswith((".cmd", ".bat"))
    if batch and CMD_UNSAFE.search(str(exe)):
        raise AgentError("the agent's path contains characters that Windows batch files can't pass safely: %s" % exe)
    dirs = []
    for d in add_dirs:
        d = str(d)
        if batch and CMD_UNSAFE.search(d):
            notes.append("Left out %s: its name has characters that are unsafe to pass to this launcher. The agent will ask before using it." % d)
        elif not Path(d).is_dir():
            notes.append("Left out %s: it doesn't exist." % d)
        else:
            dirs.append(d)
    if provider == "claude-app":                          # a link the Claude app handles itself: new Code session, folder, message filled in
        from urllib.parse import quote
        q = [("q", FIRST_MESSAGE), ("folder", str(workdir))] + [("folder", d) for d in dirs]
        return ["claude://code/new?" + "&".join("%s=%s" % (k, quote(v, safe="")) for k, v in q)], notes
    if PROVIDERS[provider]["mode"] == "editor":           # open the brief's folder in the editor
        return [exe, str(workdir)], notes
    if provider == "codex-app":                           # no link for a message exists: start the app, the message goes on the clipboard
        return ["explorer.exe", exe], notes
    if provider == "claude":
        args = [exe, FIRST_MESSAGE]                     # the message goes first: --add-dir takes several values
        if model != "default":
            args += ["--model", model]
        if effort != "default":
            args += ["--effort", effort]
        for d in dirs:
            args += ["--add-dir", d]
    elif provider == "codex":
        args = [exe]
        if workdir:
            args += ["-C", str(workdir)]
        for d in dirs:
            args += ["--add-dir", d]
        if model != "default":
            args += ["-m", model]
        if effort != "default":
            args += ["-c", 'model_reasoning_effort="%s"' % effort]
        args += [FIRST_MESSAGE]
    elif provider == "gemini":
        args = [exe]
        if model != "default":
            args += ["-m", model]
        for d in dirs:
            args += ["--include-directories", d]
        args += ["-i", FIRST_MESSAGE]
    else:                                                 # paste mode: just open the tool in the folder
        args = [exe]
    _assert_safe(args)
    return args, notes


def display(args):
    return subprocess.list2cmdline([str(a) for a in args])


def workdir_for(slug):
    d = paths.DATA / "agent" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_brief(slug, text):
    """BRIEF.md lives OUTSIDE the profile folder, so it never ends up in a published profile."""
    d = workdir_for(slug)
    (d / "BRIEF.md").write_bytes(text.encode("utf-8"))     # UTF-8, no BOM
    return d


def launch_app(provider, args):
    """Open a desktop app: the Claude link goes through the shell (only ever our own claude:// link), Codex through Explorer."""
    if provider == "claude-app":
        if not args[0].startswith("claude://code/new?"):
            raise AgentError("unexpected link")
        os.startfile(args[0])
    else:
        subprocess.Popen([str(a) for a in args], close_fds=True)


def launch_editor(args):
    """Open an editor on the brief's folder (no console window)."""
    subprocess.Popen([str(a) for a in args], close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def launch(args, workdir):
    """Open the agent in its own visible console window, in `workdir`."""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([str(a) for a in args], cwd=str(workdir), creationflags=flags, close_fds=True)
