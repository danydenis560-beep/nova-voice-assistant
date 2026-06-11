# Security Policy

Nova runs on your own PC, can execute commands, and can optionally be reached from your phone,
so we take security seriously.

## The security model

- **Local-first.** Speech-to-text runs locally. Your API keys live only in your local `.env`,
  which is git-ignored and never committed.
- **Command gate.** Nova asks for on-screen **Allow / Deny** confirmation before running PC
  commands (`NOVA_CONFIRM_SHELL=true`).
- **Phone access is off by default.** It turns on only when you set `NOVA_ACCESS_PASSWORD`.
  - Your local window is trusted over loopback (`127.0.0.1`) and never sees a login.
  - Any other device must log in with the password.
  - The session cookie is a one-way hash of the password (no secret is stored), and password
    checks are constant-time. Changing the password instantly logs every device out.
- **Bring your own keys.** You are responsible for usage and any costs on your accounts.

## Good practices for users

- Keep your `.env` private — never share it, post it, or include it when sending your folder.
- Use a **long, unique** `NOVA_ACCESS_PASSWORD` if you enable phone access.
- Prefer [Tailscale](https://tailscale.com) over exposing the port to the public internet.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead, use GitHub's private
reporting: go to the **Security** tab → **Report a vulnerability** (Draft security advisory).
We'll respond as quickly as we can.
