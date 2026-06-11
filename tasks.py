"""Nova to-do list.

A simple local task list stored in nova_tasks.json. The user can manage it by
voice (add_task / list_tasks / complete_task / delete_task) and see it on the
Personal Dashboard. Mirrors the memory.py module pattern."""
import datetime
import difflib
import json

import config

STORE = config.BASE_DIR / "nova_tasks.json"


def _load():
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(items):
    try:
        STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass


def _find(items, task):
    """Match a task by numeric id, then exact text, then closest text."""
    key = str(task).strip().lower()
    for i in items:
        if str(i.get("id")) == key:
            return i
    for i in items:
        if i.get("text", "").strip().lower() == key:
            return i
    open_items = [i for i in items if not i.get("done")]
    for i in open_items:
        if key and key in i.get("text", "").lower():
            return i
    texts = {i.get("text", "").lower(): i for i in open_items}
    close = difflib.get_close_matches(key, list(texts), n=1, cutoff=0.6)
    return texts[close[0]] if close else None


# --- operations -----------------------------------------------------------
def add_task(text, due=""):
    text = (text or "").strip()
    if not text:
        return "What should I add to your list?"
    items = _load()
    new_id = max([i.get("id", 0) for i in items], default=0) + 1
    items.append({"id": new_id, "text": text, "done": False,
                  "due": (due or "").strip(),
                  "added": datetime.date.today().isoformat()})
    _save(items)
    return f"Added to your list: {text}."


def list_tasks(include_done=False):
    items = _load()
    open_items = [i for i in items if not i.get("done")]
    if not open_items:
        return "Your task list is empty."
    parts = []
    for i in open_items:
        s = i["text"]
        if i.get("due"):
            s += f" (due {i['due']})"
        parts.append(s)
    n = len(parts)
    head = "You have 1 task: " if n == 1 else f"You have {n} tasks: "
    return head + "; ".join(parts) + "."


def complete_task(task):
    items = _load()
    i = _find(items, task)
    if i is None:
        return "I couldn't find that task."
    if i.get("done"):
        return f"'{i['text']}' is already done."
    i["done"] = True
    i["done_at"] = datetime.date.today().isoformat()
    _save(items)
    return f"Done: {i['text']}. Nice work."


def delete_task(task):
    items = _load()
    i = _find(items, task)
    if i is None:
        return "I couldn't find that task."
    items = [x for x in items if x.get("id") != i.get("id")]
    _save(items)
    return f"Removed: {i['text']}."


def clear_done():
    items = _load()
    kept = [i for i in items if not i.get("done")]
    _save(kept)
    removed = len(items) - len(kept)
    return f"Cleared {removed} completed task{'s' if removed != 1 else ''}."


# --- accessors for the dashboard / server ---------------------------------
def open_tasks():
    return [i for i in _load() if not i.get("done")]


def all_tasks():
    return _load()


# --- schemas Claude sees + dispatcher -------------------------------------
TOOLS = [
    {"name": "add_task",
     "description": "Add an item to the user's to-do list. Use when the user says to add a "
                    "task, remind them to do something, or put something on their list.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "The task, as a short phrase."},
         "due": {"type": "string", "description": "Optional due date/time in plain words, e.g. 'today', 'Friday 3pm'."}},
         "required": ["text"]}},
    {"name": "list_tasks",
     "description": "Read out the user's current open (not-yet-done) tasks. Use when they ask "
                    "what's on their list, what they have to do, or about their tasks.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "complete_task",
     "description": "Mark a task as done. Identify it by its number or by its text "
                    "(a close match is fine).",
     "input_schema": {"type": "object", "properties": {
         "task": {"type": "string", "description": "The task id or its text."}},
         "required": ["task"]}},
    {"name": "delete_task",
     "description": "Remove a task from the list entirely (by number or text). Use when the "
                    "user wants to delete or cancel a task rather than complete it.",
     "input_schema": {"type": "object", "properties": {
         "task": {"type": "string", "description": "The task id or its text."}},
         "required": ["task"]}},
]

NAMES = {"add_task", "list_tasks", "complete_task", "delete_task"}

_DISPATCH = {
    "add_task": lambda i: add_task(i.get("text", ""), i.get("due", "")),
    "list_tasks": lambda i: list_tasks(),
    "complete_task": lambda i: complete_task(i.get("task", "")),
    "delete_task": lambda i: delete_task(i.get("task", "")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown task tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Task tool '{name}' failed: {e}"
