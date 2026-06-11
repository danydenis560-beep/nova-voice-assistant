"""The things Nova can actually DO on your PC: open apps, open files/URLs,
run PowerShell. These are the client-side tools Claude calls."""
import difflib
import os
import subprocess
import webbrowser
from pathlib import Path

import briefing
import config
import files
import gcal
import memory
import messaging
import outlook
import shopify_tools
import tasks
import vision
import youtube

# Optional confirmation hook. The HUD sets this to a function that takes the
# command string and returns True to allow. When it's None, we fall back to the
# console prompt (used by the F9 console app, nova.py).
confirm_fn = None

# Optional UI-view hook. The HUD sets this to a function that takes a view name
# ("dashboard" or "hologram") and switches the on-screen view. None elsewhere.
view_fn = None

# Optional activity hook. The HUD sets this to a function called with each tool
# name as it runs, so the user can see what Nova is doing.
activity_fn = None


# --- helpers --------------------------------------------------------------
def _start_menu_shortcuts():
    """Map lowercase app name -> .lnk path, from both Start Menu locations."""
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("AppData", "")) / "Microsoft" / "Windows"
        / "Start Menu" / "Programs",
    ]
    shortcuts = {}
    for root in roots:
        if root.exists():
            for lnk in root.rglob("*.lnk"):
                shortcuts.setdefault(lnk.stem.lower(), lnk)
    return shortcuts


# --- tools ----------------------------------------------------------------
def open_application(name: str) -> str:
    """Open/launch a desktop app by name (Spotify, Chrome, Notepad, ...)."""
    q = (name or "").strip()
    if not q:
        return "No app name was given."
    ql = q.lower()
    shortcuts = _start_menu_shortcuts()

    match = shortcuts.get(ql)
    if match is None:
        contains = [s for n, s in shortcuts.items() if ql in n]
        if contains:
            match = min(contains, key=lambda s: len(s.stem))  # closest match
    if match is None:
        close = difflib.get_close_matches(ql, list(shortcuts), n=1, cutoff=0.6)
        if close:
            match = shortcuts[close[0]]

    if match is not None:
        try:
            os.startfile(str(match))
            return f"Opened {match.stem}."
        except Exception as e:  # noqa: BLE001
            return f"Found {match.stem} but couldn't open it: {e}"

    # Fallbacks: ShellExecute by name (PATH/registered apps), then Start-Process.
    try:
        os.startfile(q)
        return f"Opened {q}."
    except Exception:  # noqa: BLE001
        pass
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Start-Process '{q}'"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return f"Opened {q}."
        return f"I couldn't find an app called '{q}'."
    except Exception as e:  # noqa: BLE001
        return f"I couldn't open '{q}': {e}"


def open_path(target: str) -> str:
    """Open a file, folder, or website URL with the default handler."""
    t = (target or "").strip()
    if not t:
        return "No path or URL was given."
    if t.lower().startswith(("http://", "https://")):
        webbrowser.open(t)
        return f"Opening {t}."
    p = Path(os.path.expandvars(os.path.expanduser(t)))
    if p.exists():
        os.startfile(str(p))
        return f"Opened {p.name}."
    if "." in t and " " not in t:  # looks like a bare domain, e.g. youtube.com
        webbrowser.open("https://" + t)
        return f"Opening {t}."
    return f"I couldn't find '{target}'."


def run_powershell(command: str) -> str:
    """Run a single PowerShell command and return its output (with a confirm gate)."""
    cmd = (command or "").strip()
    if not cmd:
        return "No command was given."
    if confirm_fn is not None:
        if not confirm_fn(cmd):
            return "The user declined to run that command."
    elif config.CONFIRM_SHELL:
        print(f"\n  >> Nova wants to run this PowerShell command:\n     {cmd}")
        if input("     Allow it to run? (y/N) ").strip().lower() != "y":
            return "The user declined to run that command."
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=60,
        )
        out, err = (r.stdout or "").strip(), (r.stderr or "").strip()
        if r.returncode != 0:
            return (f"Command exited with code {r.returncode}. {err or out}")[:1500]
        return (out or "Done.")[:1500]
    except subprocess.TimeoutExpired:
        return "That command timed out after 60 seconds."
    except Exception as e:  # noqa: BLE001
        return f"Error running command: {e}"


def show_dashboard(show=True) -> str:
    """Switch the HUD between the dashboard screen and the main hologram."""
    if view_fn is None:
        return "The dashboard only appears in the Nova window."
    try:
        view_fn("dashboard" if show else "hologram")
    except Exception as e:  # noqa: BLE001
        return f"I couldn't switch the view: {e}"
    return "Here's your dashboard." if show else "Back to the main view."


# --- schemas Claude sees + dispatcher -------------------------------------
TOOLS = [
    {
        "name": "open_application",
        "description": (
            "Open or launch a desktop application on the user's Windows PC by "
            "its name, e.g. 'Spotify', 'Chrome', 'Notepad', 'Calculator', "
            "'Visual Studio Code'. Use this whenever the user asks to open, "
            "launch, or start an app."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The application name."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "open_path",
        "description": (
            "Open a file, folder, or website URL with the default handler. "
            "Use for opening a website (e.g. 'https://youtube.com'), a folder "
            "(e.g. 'C:\\\\Users\\\\me\\\\Downloads'), or a document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "A file path, folder path, or URL.",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "run_powershell",
        "description": (
            "Run a single-line Windows PowerShell command on the user's PC and "
            "return its output. Use for system actions and info not covered by "
            "the other tools, e.g. checking battery, setting volume, listing "
            "files, creating a folder. The user is asked to confirm before "
            "anything runs, so prefer simple, safe commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "A single-line PowerShell command.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "show_dashboard",
        "description": (
            "Show or hide the user's personal dashboard screen in the Nova "
            "window (weather, to-do list, revenue, and more). Use when the user "
            "asks to see their dashboard, open the dashboard, show their day, or "
            "go back to the main view."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "show": {
                    "type": "boolean",
                    "description": "true to open the dashboard, false to return to the hologram. Defaults to true.",
                }
            },
        },
    },
]

_DISPATCH = {
    "open_application": lambda i: open_application(i.get("name", "")),
    "open_path": lambda i: open_path(i.get("target", "")),
    "run_powershell": lambda i: run_powershell(i.get("command", "")),
    "show_dashboard": lambda i: show_dashboard(i.get("show", True)),
}


def dispatch(name: str, tool_input: dict):
    # Returns a string for most tools, or a list of content blocks (text +
    # image) for the vision tools — both are valid tool_result content.
    if activity_fn is not None:
        try:
            activity_fn(name)
        except Exception:  # noqa: BLE001
            pass
    if name.startswith("shopify_"):
        return shopify_tools.dispatch(name, tool_input or {})
    if name in memory.NAMES:
        return memory.dispatch(name, tool_input or {})
    if name in tasks.NAMES:
        return tasks.dispatch(name, tool_input or {})
    if name in gcal.NAMES:
        return gcal.dispatch(name, tool_input or {})
    if name in youtube.NAMES:
        return youtube.dispatch(name, tool_input or {})
    if name in briefing.NAMES:
        return briefing.dispatch(name, tool_input or {})
    if name in files.NAMES:
        return files.dispatch(name, tool_input or {})
    if name in messaging.NAMES:
        return messaging.dispatch(name, tool_input or {})
    if name in outlook.NAMES:
        return outlook.dispatch(name, tool_input or {})
    if name in vision.NAMES:
        return vision.dispatch(name, tool_input or {})
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Tool '{name}' failed: {e}"
