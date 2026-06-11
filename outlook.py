"""Outlook / Microsoft 365 email for Nova via Microsoft Graph.

Auth = MSAL device-code flow: the user signs in once at microsoft.com/devicelogin
(no password stored here), and the refresh token is cached in outlook_token.json
so Nova stays signed in. Needs an Azure app registration → OUTLOOK_CLIENT_ID +
OUTLOOK_TENANT_ID, with delegated Graph permissions Mail.Read + Mail.Send.

Tools: check_email (read recent/unread), send_email (confirm-gated). unread_count()
feeds the daily briefing."""
import httpx

import config

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "Mail.Send"]
CACHE_FILE = config.BASE_DIR / "outlook_token.json"

# Set by server.py to hud_confirm; gates sending so a misheard command can't email.
confirm_fn = None


def is_configured():
    return bool((config.OUTLOOK_CLIENT_ID or "").strip())


def _authority():
    tenant = (config.OUTLOOK_TENANT_ID or "common").strip() or "common"
    return f"https://login.microsoftonline.com/{tenant}"


def _build_app():
    import msal
    cache = msal.SerializableTokenCache()
    try:
        if CACHE_FILE.exists():
            cache.deserialize(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    app = msal.PublicClientApplication(
        (config.OUTLOOK_CLIENT_ID or "").strip(), authority=_authority(), token_cache=cache)
    return app, cache


def _save(cache):
    try:
        if cache.has_state_changed:
            CACHE_FILE.write_text(cache.serialize(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _token():
    """A valid access token from the cached account (silent refresh), or (None, msg)."""
    if not is_configured():
        return None, "Outlook isn't connected yet."
    try:
        app, cache = _build_app()
        accounts = app.get_accounts()
        if not accounts:
            return None, "Outlook isn't signed in yet. Ask me to set up Outlook."
        res = app.acquire_token_silent(SCOPES, account=accounts[0])
        _save(cache)
        if res and "access_token" in res:
            return res["access_token"], None
        return None, "Outlook sign-in expired. Ask me to set up Outlook again."
    except Exception as e:  # noqa: BLE001
        return None, f"Outlook auth error: {e}"


def device_login():
    """Run the one-time device-code sign-in (blocks until the user approves).
    Prints the code/URL to stdout for a setup script to relay. Returns a dict."""
    app, cache = _build_app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        return {"ok": False, "error": str(flow)}
    print("DEVICE_LOGIN " + flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)  # blocks ~until approved/timeout
    _save(cache)
    if "access_token" in result:
        who = (result.get("id_token_claims") or {}).get("preferred_username", "")
        return {"ok": True, "account": who}
    return {"ok": False, "error": result.get("error_description", str(result))}


def signed_in():
    try:
        app, _ = _build_app()
        return bool(app.get_accounts())
    except Exception:  # noqa: BLE001
        return False


# --- read -----------------------------------------------------------------
def check_email(count=5, unread_only=True):
    tok, err = _token()
    if err:
        return err
    params = {"$top": max(1, min(int(count or 5), 15)),
              "$select": "subject,from,receivedDateTime,isRead,bodyPreview",
              "$orderby": "receivedDateTime desc"}
    if unread_only:
        params["$filter"] = "isRead eq false"
    try:
        r = httpx.get(f"{GRAPH}/me/mailFolders/inbox/messages",
                      headers={"Authorization": f"Bearer {tok}"}, params=params, timeout=20)
    except Exception as e:  # noqa: BLE001
        return f"Couldn't reach Outlook: {e}"
    if r.status_code >= 400:
        return f"Outlook returned an error ({r.status_code})."
    msgs = r.json().get("value", [])
    if not msgs:
        return "No unread emails." if unread_only else "Your inbox looks empty."
    lines = []
    for m in msgs:
        who = ((m.get("from") or {}).get("emailAddress") or {}).get("name", "someone")
        subj = m.get("subject") or "(no subject)"
        lines.append(f"from {who}: {subj}")
    head = f"You have {len(msgs)} {'unread ' if unread_only else ''}email{'s' if len(msgs) != 1 else ''}: "
    return head + "; ".join(lines) + "."


def unread_count():
    tok, err = _token()
    if err:
        return None
    try:
        r = httpx.get(f"{GRAPH}/me/mailFolders/inbox/messages/$count",
                      headers={"Authorization": f"Bearer {tok}", "ConsistencyLevel": "eventual"},
                      params={"$filter": "isRead eq false"}, timeout=15)
        if r.status_code < 400:
            return int(r.text)
    except Exception:  # noqa: BLE001
        pass
    return None


# --- send -----------------------------------------------------------------
def send_email(to, subject="", body=""):
    tok, err = _token()
    if err:
        return err
    recips = [a.strip() for a in str(to or "").replace(";", ",").split(",") if a.strip()]
    if not recips:
        return "Who should I send it to?"
    if confirm_fn is not None and not confirm_fn(
            f"Send email to {', '.join(recips)}?\nSubject: {subject}\n\n{body}"):
        return "Okay, I didn't send it."
    msg = {"message": {
        "subject": subject or "(no subject)",
        "body": {"contentType": "Text", "content": body or ""},
        "toRecipients": [{"emailAddress": {"address": a}} for a in recips]}}
    try:
        r = httpx.post(f"{GRAPH}/me/sendMail",
                       headers={"Authorization": f"Bearer {tok}"}, json=msg, timeout=20)
    except Exception as e:  # noqa: BLE001
        return f"Couldn't reach Outlook: {e}"
    if r.status_code in (200, 202):
        return f"Email sent to {', '.join(recips)}."
    return f"Outlook wouldn't send it ({r.status_code})."


TOOLS = [
    {"name": "check_email",
     "description": "Read the user's recent Outlook emails (unread by default). Use when they ask "
                    "to check email, read their inbox, or if they have new mail.",
     "input_schema": {"type": "object", "properties": {
         "count": {"type": "integer", "description": "How many to read (default 5)."},
         "unread_only": {"type": "boolean", "description": "Only unread (default true)."}}}},
    {"name": "send_email",
     "description": "Send an email from the user's Outlook account. Use when they ask to email "
                    "or send a message to someone by email address.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string", "description": "Recipient email address(es), comma-separated."},
         "subject": {"type": "string", "description": "The subject line."},
         "body": {"type": "string", "description": "The email body text."}},
         "required": ["to", "body"]}},
]

NAMES = {"check_email", "send_email"}

_DISPATCH = {
    "check_email": lambda i: check_email(i.get("count", 5), i.get("unread_only", True)),
    "send_email": lambda i: send_email(i.get("to", ""), i.get("subject", ""), i.get("body", "")),
}


def dispatch(name, tool_input):
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown email tool: {name}"
    try:
        return fn(tool_input or {})
    except Exception as e:  # noqa: BLE001
        return f"Email tool '{name}' failed: {e}"
