# Contributing to Nova

Thanks for your interest in improving Nova! This is a friendly, beginner-welcoming project.

## Ways to help

- 🐛 **Report a bug** — open an [issue](../../issues) and describe what happened, what you
  expected, and your Windows + Python version.
- 💡 **Suggest a feature** — open an issue describing the idea and why it's useful.
- 🔧 **Send a pull request** — fix a bug, add a feature, or improve the docs.

## Setting up a dev environment

You'll need **Windows 10/11** and **Python 3.12**.

```powershell
git clone https://github.com/danydenis560-beep/nova-voice-assistant.git
cd nova-voice-assistant

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env       # then paste your ANTHROPIC_API_KEY into .env
python launch_nova.pyw
```

## Making a change

1. **Fork** the repo and create a branch: `git checkout -b my-change`.
2. Make your edit. Keep the style of the surrounding code — small, readable functions and
   plain-language comments. Match the existing naming.
3. **Test it** by running Nova and exercising the feature you touched.
4. **Never commit secrets.** Your `.env`, tokens, voiceprint, logs, and runtime `*.json` are
   already covered by `.gitignore` — please keep it that way. Only `.env.example` is committed.
5. **Commit** with a clear message and **open a pull request** describing what changed and why.

## Code of conduct

Be kind and constructive. Assume good intent. We want this to be a welcoming place for people
building their first AI assistant.
