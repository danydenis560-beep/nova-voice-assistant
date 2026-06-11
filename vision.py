"""Nova's eyes.

Lets Nova actually SEE: capture the screen, read a document or image file,
and take a webcam photo. Each tool returns an image (or text) straight back to
Claude as the tool result, so the brain looks at it with full conversation
context and answers in the user's voice.

Design notes:
- All heavy imports (Pillow, OpenCV, PyMuPDF) are done lazily inside the
  functions, so `import vision` never fails and never slows server boot. Any
  capture problem comes back as a friendly tool-result string, not a crash.
- Images are downscaled to MAX_EDGE on the long side. Claude resizes anything
  bigger than ~1568px anyway, so this just saves upload time and tokens with no
  quality loss. brain.py also prunes old images out of the chat history.
"""
import base64
import io
import os
from pathlib import Path

# Claude scales images so the long edge is <= ~1568px; match that ourselves.
MAX_EDGE = 1568
# Cap how much document text we hand back in one go (keeps replies snappy).
MAX_TEXT_CHARS = 16000

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json",
    ".xml", ".html", ".htm", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".java", ".rb", ".go", ".rs", ".php", ".css", ".scss", ".sql", ".sh",
    ".bat", ".ps1", ".r", ".tex", ".env",
}


# --- image helpers --------------------------------------------------------
def _downscale(img, max_edge=MAX_EDGE):
    from PIL import Image
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img
    scale = max_edge / float(longest)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _img_block(img, fmt="PNG"):
    """Encode a PIL image as an Anthropic base64 image content block."""
    if fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    media = "image/jpeg" if fmt == "JPEG" else "image/png"
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def _clip_text(s):
    if len(s) > MAX_TEXT_CHARS:
        return s[:MAX_TEXT_CHARS] + "\n\n[...truncated, file is longer...]"
    return s


# --- see the screen -------------------------------------------------------
def see_screen() -> "list | str":
    """Screenshot the user's primary monitor and hand it to Claude."""
    try:
        from PIL import ImageGrab
    except Exception as e:  # noqa: BLE001
        return f"I couldn't load screen capture: {e}"
    try:
        img = ImageGrab.grab()  # primary monitor (all_screens=False)
    except Exception as e:  # noqa: BLE001
        return f"I couldn't capture the screen: {e}"
    if img is None:
        return "I couldn't capture the screen."
    w0, h0 = img.size
    img = _downscale(img)
    return [
        {"type": "text", "text": f"Here is what is currently on the screen ({w0}x{h0})."},
        _img_block(img, "PNG"),
    ]


# --- read a file ----------------------------------------------------------
def _resolve(path):
    """Find a file by full path, or by bare name on the common user folders."""
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return None
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if p.exists():
        return p
    if not p.is_absolute():
        home = Path.home()
        for folder in ("Desktop", "Downloads", "Documents", "Pictures"):
            cand = home / folder / raw
            if cand.exists():
                return cand
    return None


def _read_image_file(p):
    from PIL import Image
    img = Image.open(str(p))
    img.load()  # decode first frame of animated formats
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    w0, h0 = img.size
    img = _downscale(img)
    return [
        {"type": "text", "text": f"Here is the image {p.name} ({w0}x{h0})."},
        _img_block(img, "PNG"),
    ]


def _read_text(p):
    txt = p.read_text(encoding="utf-8", errors="replace")
    return _clip_text(f"Contents of {p.name}:\n\n{txt}")


def _try_text(p):
    """Best-effort: read an unknown file as text unless it looks binary."""
    try:
        data = p.read_bytes()[:200_000]
    except Exception:  # noqa: BLE001
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def _read_pdf(p):
    n = 0
    # Preferred: PyMuPDF (text, and can render scanned pages to images).
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001
        fitz = None
    if fitz is not None:
        doc = fitz.open(str(p))
        n = doc.page_count
        full = "\n".join(page.get_text() for page in doc).strip()
        if len(full) >= 30:
            doc.close()
            return _clip_text(f"Contents of {p.name} ({n} pages):\n\n{full}")
        # Scanned/image-only PDF: show the first few pages as pictures.
        blocks = [{"type": "text",
                   "text": f"{p.name} has no selectable text; here are its first pages:"}]
        for i in range(min(3, n)):
            pix = doc[i].get_pixmap(dpi=150)
            from PIL import Image
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            blocks.append(_img_block(_downscale(img), "PNG"))
        doc.close()
        return blocks
    # Fallback: pypdf (text only).
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        return ("I found the PDF but I need a PDF reader installed to open it. "
                "Ask me to enable PDF reading and I'll set it up — it's quick.")
    reader = PdfReader(str(p))
    full = "\n".join((pg.extract_text() or "") for pg in reader.pages).strip()
    if not full:
        return ("That PDF looks like scanned images with no selectable text. "
                "Enable PDF reading (PyMuPDF) and I can look at the pages directly.")
    return _clip_text(f"Contents of {p.name} ({len(reader.pages)} pages):\n\n{full}")


def _read_docx(p):
    # Preferred: python-docx if present.
    try:
        import docx  # python-docx
        d = docx.Document(str(p))
        full = "\n".join(par.text for par in d.paragraphs).strip()
        if full:
            return _clip_text(f"Contents of {p.name}:\n\n{full}")
    except Exception:  # noqa: BLE001
        pass
    # No-dependency fallback: pull the text out of the .docx zip directly.
    try:
        import html
        import re
        import zipfile
        with zipfile.ZipFile(str(p)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
        txt = html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()
        if txt:
            return _clip_text(f"Contents of {p.name}:\n\n{txt}")
    except Exception as e:  # noqa: BLE001
        return f"I couldn't read that Word document: {e}"
    return f"I couldn't find any text in {p.name}."


def read_document(path: str) -> "list | str":
    """Read a file (document, code/text, or image) and show it to Claude."""
    p = _resolve(path)
    if p is None:
        return f"I couldn't find a file called '{path}'."
    if p.is_dir():
        return f"'{p.name}' is a folder, not a file."
    suf = p.suffix.lower()
    try:
        if suf in IMAGE_SUFFIXES:
            return _read_image_file(p)
        if suf == ".pdf":
            return _read_pdf(p)
        if suf == ".docx":
            return _read_docx(p)
        if suf in TEXT_SUFFIXES:
            return _read_text(p)
        txt = _try_text(p)
        if txt is not None:
            return _clip_text(f"Contents of {p.name}:\n\n{txt}")
        return (f"I can see {p.name}, but I don't know how to read a "
                f"'{suf or 'file with no extension'}' as text.")
    except Exception as e:  # noqa: BLE001
        return f"I ran into a problem reading {p.name}: {e}"


# --- look through the webcam ---------------------------------------------
def look_camera() -> "list | str":
    """Grab one frame from the default webcam and hand it to Claude."""
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return ("I don't have webcam support installed yet. Ask me to enable "
                "the camera and I'll set it up — it's a quick one-time install.")
    cap = None
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # DirectShow opens fast on Windows
        if cap is None or not cap.isOpened():
            return "I couldn't open the webcam. Is it connected and not in use by another app?"
        frame = None
        for _ in range(6):  # discard a few frames so exposure/focus settle
            ok, f = cap.read()
            if ok:
                frame = f
        if frame is None:
            return "I couldn't read a frame from the webcam."
        from PIL import Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = _downscale(Image.fromarray(rgb))
        w0, h0 = img.size
        return [
            {"type": "text", "text": f"Here is the webcam photo ({w0}x{h0})."},
            _img_block(img, "JPEG"),
        ]
    except Exception as e:  # noqa: BLE001
        return f"I had a problem using the webcam: {e}"
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:  # noqa: BLE001
            pass


# --- schemas Claude sees + dispatcher -------------------------------------
TOOLS = [
    {
        "name": "see_screen",
        "description": (
            "Take a screenshot of what is currently on the user's screen and "
            "look at it. Use this whenever the user asks what's on their screen, "
            "to read or explain something they're looking at, to help with an "
            "app, window, error message, or webpage they can see, or when they "
            "say things like 'what is this', 'look at this', 'what am I looking "
            "at', or 'help me with what's on my screen'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_document",
        "description": (
            "Open and read a file on the user's PC so you can see its contents. "
            "Works for documents (PDF, Word .docx), text and code files (.txt, "
            ".md, .csv, .json, .py, ...), and images (.png, .jpg, ...). Use when "
            "the user asks you to read, summarize, check, review, or look at a "
            "specific file. Give the file path; a bare filename is also tried on "
            "the Desktop, Downloads, Documents, and Pictures folders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file, or just its name.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "look_camera",
        "description": (
            "Take a photo with the PC's webcam and look at it. Use when the user "
            "asks you to look at them, look through the camera, see the room, or "
            "look at something they're holding up to the webcam."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

NAMES = {"see_screen", "read_document", "look_camera"}

_DISPATCH = {
    "see_screen": lambda i: see_screen(),
    "read_document": lambda i: read_document(i.get("path", "")),
    "look_camera": lambda i: look_camera(),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown vision tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Vision tool '{name}' failed: {e}"
