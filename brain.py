"""The brain: talks to Claude, runs the tool-use loop, returns a spoken reply."""
import datetime

import anthropic

import briefing
import config
import files
import gcal
import memory
import messaging
import outlook
import shopify_tools
import tasks
import tools
import vision
import youtube

# Anthropic's server-side web search. Claude runs it for us and summarizes the
# results — no extra code or API key needed.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 4}
_SHOP = shopify_tools.TOOLS if shopify_tools.is_configured() else []
_DASH = (tasks.TOOLS + gcal.TOOLS + youtube.TOOLS + briefing.TOOLS + files.TOOLS
         + messaging.TOOLS + outlook.TOOLS)
ALL_TOOLS = tools.TOOLS + [WEB_SEARCH_TOOL] + memory.TOOLS + _DASH + vision.TOOLS + _SHOP
# Tool set without run_powershell — used by the HUD, which has no console to
# confirm shell commands in. (open apps / files / URLs + web search + memory +
# tasks + calendar + youtube + vision + Shopify.)
SAFE_TOOLS = [t for t in tools.TOOLS if t["name"] != "run_powershell"] + [WEB_SEARCH_TOOL] + memory.TOOLS + _DASH + vision.TOOLS + _SHOP

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _system_prompt() -> str:
    now = datetime.datetime.now().astimezone()
    shop = (" You can also answer read-only questions about the user's Shopify "
            "store — orders, sales, products, and inventory.") if shopify_tools.is_configured() else ""
    mem = memory.context_block()
    return (
        "You are Nova, a voice assistant that controls the user's Windows 11 "
        "PC and speaks back to them.\n"
        f"The current date and time is {now:%A, %B %d, %Y, %I:%M %p %Z}.\n"
        "You can open apps, open files/folders/URLs, run PowerShell commands, "
        "and search the web. You can also SEE: take a screenshot of the screen, "
        "read a document or image file, and look through the webcam. You keep the "
        "user's to-do list (add, list, complete tasks), check their Google "
        "Calendar (check_calendar), report their YouTube channel stats "
        "(youtube_stats), give a spoken daily briefing (daily_briefing) and "
        "schedule it (set_briefing_schedule), and show their personal dashboard "
        "with show_dashboard (weather, tasks, calendar, and more). You can save "
        "content to files on the PC including PDFs (save_file), and post messages "
        "to their Telegram (send_telegram) and Discord (send_discord). You can "
        "read and send the user's Outlook email (check_email, send_email)." + shop + "\n"
        "Rules:\n"
        "- When you use daily_briefing, read its result out loud in full, word "
        "for word — don't shorten or summarize it.\n"
        "- When the user asks what's on their screen, to read or look at "
        "something, or refers to what they're seeing, use your vision tools "
        "(see_screen, read_document, look_camera) to actually look before you "
        "answer. Then describe what you see in plain spoken language.\n"
        "- Your replies are read aloud by text-to-speech, so respond in 1-3 "
        "short, natural spoken sentences. No markdown, no bullet points, no "
        "code blocks, no emoji, and never read out raw URLs.\n"
        "- Reply in the same language the user speaks to you — English, French, or "
        "Haitian Creole (Kreyòl ayisyen). If they speak Creole, reply in natural "
        "Haitian Creole.\n"
        "- When asked to open or launch something, just do it with the tools, "
        "then briefly confirm in one sentence.\n"
        "- Use web search for current facts, news, prices, or research, then "
        "say the answer out loud in plain language.\n"
        "- When the user shares a goal, project, business, or preference (or "
        "says 'remember'), save it with the remember tool, then briefly confirm.\n"
        "- Don't explain your reasoning or your plan; give only the final "
        "spoken answer."
        + ("\n\n" + mem if mem else "")
    )


def _spoken_text(content) -> str:
    parts = [b.text for b in content if getattr(b, "type", None) == "text"]
    return " ".join(p.strip() for p in parts if p and p.strip())


def _trim_history(messages, keep=24):
    """Keep history bounded without cutting between a tool_use and its result.

    A user message whose content is a plain string is always a clean boundary
    (that's a spoken utterance, never a tool_result), so start from one.
    """
    if len(messages) <= keep:
        return
    start = len(messages) - keep
    while start < len(messages):
        m = messages[start]
        if m["role"] == "user" and isinstance(m["content"], str):
            break
        start += 1
    if start < len(messages):
        del messages[:start]


def _content_has_image(content):
    if not isinstance(content, list):
        return False
    for b in content:
        if isinstance(b, dict):
            if b.get("type") == "image":
                return True
            if b.get("type") == "tool_result" and _content_has_image(b.get("content")):
                return True
    return False


def _strip_images(content):
    if not isinstance(content, list):
        return content
    out = []
    for b in content:
        if isinstance(b, dict):
            if b.get("type") == "image":
                out.append({"type": "text",
                            "text": "[earlier image omitted — ask me to look again]"})
                continue
            if b.get("type") == "tool_result":
                b = {**b, "content": _strip_images(b.get("content"))}
        out.append(b)
    return out


def _prune_old_images(messages, keep_last=1):
    """Drop screenshots/photos from all but the most recent vision result, so we
    don't re-upload heavy images on every turn (a follow-up about the last thing
    seen still works; 'look again' just re-captures)."""
    idxs = [i for i, m in enumerate(messages) if _content_has_image(m.get("content"))]
    for i in idxs[:-keep_last] if keep_last > 0 else idxs:
        messages[i]["content"] = _strip_images(messages[i]["content"])


def _battr(block, field):
    if isinstance(block, dict):
        return block.get(field)
    return getattr(block, field, None)


def _sanitize_history(messages):
    """Drop orphaned tool_use / tool_result blocks (e.g. a server-side web search
    or code execution whose result never arrived) so one broken turn can't make
    every future request fail with a 400. Removes any message left empty."""
    have_use, have_result = set(), set()
    for m in messages:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            t = _battr(b, "type") or ""
            if t in ("tool_use", "server_tool_use"):
                if _battr(b, "id"):
                    have_use.add(_battr(b, "id"))
            elif t.endswith("tool_result"):
                if _battr(b, "tool_use_id"):
                    have_result.add(_battr(b, "tool_use_id"))
    keep = []
    for m in messages:
        c = m.get("content")
        if not isinstance(c, list):
            keep.append(m)
            continue
        new = []
        for b in c:
            t = _battr(b, "type") or ""
            if t in ("tool_use", "server_tool_use") and _battr(b, "id") not in have_result:
                continue  # orphaned tool call — drop it
            if t.endswith("tool_result") and _battr(b, "tool_use_id") not in have_use:
                continue  # orphaned result — drop it
            new.append(b)
        if new:
            m["content"] = new
            keep.append(m)
    messages[:] = keep


def _last_user_text(messages):
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return None


def respond(messages, tool_list=None) -> str:
    """Run the agentic loop over the (mutated) conversation list; return reply text."""
    client = _get_client()
    tool_list = tool_list if tool_list is not None else ALL_TOOLS
    _trim_history(messages)
    _prune_old_images(messages)
    _sanitize_history(messages)
    continuations = 0
    recovered = False

    while True:
        try:
            resp = client.messages.create(
                model=config.MODEL,
                max_tokens=1024,
                system=_system_prompt(),
                messages=messages,
                tools=tool_list,
                thinking={"type": "disabled"},  # snappy spoken replies
            )
        except anthropic.BadRequestError as e:
            emsg = str(e).lower()
            if "credit balance" in emsg or "billing" in emsg:
                return ("I've run out of Anthropic credits, so I can't think right now. "
                        "Please top up the account at console dot anthropic dot com, and "
                        "then I'll be right back.")
            # Only reset on a genuine message/tool-structure problem (e.g. an
            # orphaned server-tool block), not on other 400s.
            structural = ("tool_use" in emsg or "tool_result" in emsg or "messages." in emsg)
            if structural and not recovered:
                recovered = True
                last = _last_user_text(messages)
                messages.clear()
                if last:
                    messages.append({"role": "user", "content": last})
                continuations = 0
                continue
            raise
        # Always append the full assistant turn (preserves tool_use / web-search blocks).
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "pause_turn":
            # Server-side tool (e.g. web search) paused mid-loop — re-send to continue.
            continuations += 1
            if continuations > 8:
                break
            continue

        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":  # client tools; server tools handled by the API
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tools.dispatch(block.name, block.input),
                    })
            messages.append({"role": "user", "content": results})
            continue

        break  # end_turn

    return _spoken_text(messages[-1]["content"]) or "Sorry, I didn't catch that."
