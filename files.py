"""Let Nova save content to files on the PC — text, code, Markdown, CSV, JSON,
HTML, and PDF. Defaults to the Desktop so the user can find what was saved.

PDFs are rendered with PyMuPDF's Story/DocumentWriter (auto-paginates long text)."""
import os
from pathlib import Path

# Extensions we'll happily write as plain UTF-8 text.
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".xml",
    ".html", ".htm", ".yaml", ".yml", ".ini", ".cfg", ".toml", ".py", ".js",
    ".ts", ".css", ".sql", ".sh", ".bat", ".ps1", ".c", ".cpp", ".java", ".rb",
    ".go", ".rs", ".php", ".r", ".tex", ".srt", ".vtt",
}


def _resolve_folder(folder):
    home = Path.home()
    f = (folder or "").strip().strip('"')
    aliases = {"": home / "Desktop", "desktop": home / "Desktop",
               "documents": home / "Documents", "docs": home / "Documents",
               "downloads": home / "Downloads", "pictures": home / "Pictures"}
    if f.lower() in aliases:
        return aliases[f.lower()]
    p = Path(os.path.expandvars(os.path.expanduser(f)))
    if p.is_absolute() and (p.exists() or p.parent.exists()):
        return p
    return home / "Desktop" / f  # treat as a subfolder name on the Desktop


def _text_to_pdf(path, content):
    """Render plain text to a paginated PDF via PyMuPDF Story."""
    import html
    import fitz
    safe = html.escape(content or "")
    paras = "".join(
        (f"<p style='margin:0 0 8pt 0'>{ln}</p>" if ln.strip() else "<p style='margin:0 0 8pt 0'>&nbsp;</p>")
        for ln in safe.split("\n")
    )
    htmldoc = ("<html><body style=\"font-family:sans-serif;font-size:11pt;"
               f"line-height:1.45;color:#111\">{paras}</body></html>")
    story = fitz.Story(html=htmldoc)
    writer = fitz.DocumentWriter(path)
    mediabox = fitz.paper_rect("letter")
    where = mediabox + (54, 54, -54, -54)  # 0.75" margins
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


def save_file(filename, content="", folder=""):
    """Save `content` to a file. Text extensions are written directly; .pdf is
    rendered. Bare names land on the Desktop (or the given folder)."""
    name = (filename or "").strip().strip('"').strip("'")
    if not name:
        return "What should I name the file?"
    content = "" if content is None else str(content)
    p = Path(os.path.expandvars(os.path.expanduser(name)))
    if not p.is_absolute():
        base = _resolve_folder(folder)
        p = base / name
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return f"I couldn't create that folder: {e}"
    if not p.suffix:
        p = p.with_suffix(".txt")
    suf = p.suffix.lower()
    try:
        if suf == ".pdf":
            _text_to_pdf(str(p), content)
        elif suf in TEXT_SUFFIXES:
            p.write_text(content, encoding="utf-8")
        else:
            # Unknown extension: still write the text content (best effort).
            p.write_text(content, encoding="utf-8")
        size = p.stat().st_size
        return f"Saved '{p.name}' to {p.parent} ({size:,} bytes)."
    except Exception as e:  # noqa: BLE001
        return f"I couldn't save that file: {e}"


TOOLS = [
    {"name": "save_file",
     "description": (
         "Save text content to a file on the user's PC — notes, a summary, a list, "
         "code, a report, etc. Supports PDF (.pdf) and text formats (.txt, .md, "
         ".csv, .json, .html, code files...). Use when the user asks you to save, "
         "write, export, or put something into a file or PDF. Files go to the "
         "Desktop unless a folder is given. Provide the full content to write."
     ),
     "input_schema": {"type": "object", "properties": {
         "filename": {"type": "string", "description": "File name with extension, e.g. 'meeting-notes.pdf' or 'todo.txt'."},
         "content": {"type": "string", "description": "The full text/content to write into the file."},
         "folder": {"type": "string", "description": "Optional: 'desktop' (default), 'documents', 'downloads', or a full folder path."}},
         "required": ["filename", "content"]}},
]

NAMES = {"save_file"}

_DISPATCH = {
    "save_file": lambda i: save_file(i.get("filename", ""), i.get("content", ""), i.get("folder", "")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown file tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"File tool '{name}' failed: {e}"
