"""Remote-access security for Nova.

Nova can run shell commands, so the server must never be reachable from the
network without proof you know the access password. The rules are simple:

  * Your own PC window connects over 127.0.0.1 (loopback) and is ALWAYS trusted
    — it never sees a login screen.
  * Any other device (your phone over Tailscale or home Wi-Fi) must log in once
    with ACCESS_PASSWORD. Logging in stores a cookie token so it stays signed in.
  * With no password set, remote access is impossible (the token can never match)
    and the server only binds to this PC anyway — so this is safe by default.

The cookie token is derived from the password (a one-way hash), so it survives
restarts with no stored secrets, and CHANGING the password instantly logs every
phone back out.
"""
import hashlib
import hmac

import config

# Loopback addresses that mean "a process on this same PC" — always trusted.
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def is_local(host: str) -> bool:
    """True if the request came from this PC itself (the local Nova window)."""
    return (host or "") in _LOCAL_HOSTS


def remote_enabled() -> bool:
    """True once the user has set an access password (phone control is possible)."""
    return bool(config.ACCESS_PASSWORD)


def token_for() -> str:
    """A stable cookie value that proves knowledge of the current password.
    Changes whenever the password changes (which logs old devices out)."""
    pw = config.ACCESS_PASSWORD or ""
    return hashlib.sha256(("nova-access-v1::" + pw).encode("utf-8")).hexdigest()


def check_password(pw: str) -> bool:
    """True if `pw` matches the configured access password (constant-time)."""
    if not config.ACCESS_PASSWORD:
        return False
    return hmac.compare_digest(pw or "", config.ACCESS_PASSWORD)


def check_token(token: str) -> bool:
    """True if a device's cookie token is valid (constant-time)."""
    if not config.ACCESS_PASSWORD:
        return False
    return hmac.compare_digest(token or "", token_for())
