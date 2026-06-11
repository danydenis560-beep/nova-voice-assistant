"""Nova long-term memory.

Remembers the user's goals, projects, businesses, and preferences across
conversations in a local JSON file (nova_memory.json), and surfaces them to
the brain on every turn so Nova stays personal and consistent."""
import datetime
import json

import config

STORE = config.BASE_DIR / "nova_memory.json"
CATS = ("goal", "project", "business", "preference", "note")


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


def remember(category, content):
    content = (content or "").strip()
    if not content:
        return "Nothing to remember."
    items = _load()
    cat = (category or "note").strip().lower()
    if cat not in CATS:
        cat = "note"
    new_id = max([i.get("id", 0) for i in items], default=0) + 1
    items.append({"id": new_id, "category": cat, "content": content,
                  "added": datetime.date.today().isoformat()})
    _save(items)
    return f"Got it — I'll remember that ({cat})."


def update_memory(mem_id, content):
    items = _load()
    for i in items:
        if str(i.get("id")) == str(mem_id):
            i["content"] = (content or "").strip()
            _save(items)
            return "Updated that memory."
    return "I couldn't find that memory."


def forget_memory(mem_id):
    items = _load()
    kept = [i for i in items if str(i.get("id")) != str(mem_id)]
    _save(kept)
    return "Forgotten." if len(kept) < len(items) else "I couldn't find that memory."


def context_block():
    """Format all memories for injection into the system prompt."""
    items = _load()
    if not items:
        return ""
    groups = {}
    for i in items:
        groups.setdefault(i.get("category", "note"), []).append(i)
    lines = ["What you remember about the user (use this to personalize help):"]
    for cat in list(CATS) + [c for c in groups if c not in CATS]:
        if cat in groups:
            lines.append(f"{cat.capitalize()}s:")
            for i in groups[cat]:
                lines.append(f"  - [#{i['id']}] {i['content']}")
    return "\n".join(lines)


TOOLS = [
    {"name": "remember",
     "description": "Save a lasting fact about the user — a goal, project, business, or "
                    "preference — so you remember it in future conversations. Use this "
                    "whenever the user shares something personal or ongoing, or says "
                    "'remember'.",
     "input_schema": {"type": "object", "properties": {
         "category": {"type": "string", "enum": list(CATS), "description": "Type of memory."},
         "content": {"type": "string", "description": "The fact to remember, as a clear sentence."}},
         "required": ["content"]}},
    {"name": "update_memory",
     "description": "Update an existing memory by its id (ids show as [#N] in what you remember).",
     "input_schema": {"type": "object", "properties": {
         "id": {"type": "integer", "description": "The memory id."},
         "content": {"type": "string", "description": "The new content."}},
         "required": ["id", "content"]}},
    {"name": "forget_memory",
     "description": "Delete a memory by its id when the user asks you to forget something.",
     "input_schema": {"type": "object", "properties": {
         "id": {"type": "integer", "description": "The memory id to forget."}},
         "required": ["id"]}},
]

NAMES = {"remember", "update_memory", "forget_memory"}

_DISPATCH = {
    "remember": lambda i: remember(i.get("category", "note"), i.get("content", "")),
    "update_memory": lambda i: update_memory(i.get("id"), i.get("content", "")),
    "forget_memory": lambda i: forget_memory(i.get("id")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown memory tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Memory tool '{name}' failed: {e}"
