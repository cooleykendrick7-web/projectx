# Project X

Ken's private AI website. Password-protected, single user. Chat with streaming
replies, multiple conversations, and a fully editable personality.

## Brain

The AI behind it is OpenRouter. Paste a free API key in Settings
(openrouter.ai → Keys — no card needed). Free `:free` models get roughly
50 requests/day; a one-time $10 top-up raises that to ~1,000/day.

Default model: `nvidia/nemotron-3-ultra-550b-a55b:free`.

## Run locally

```
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000 — log in with the admin password (given to Ken directly).

## Deploy

Render Blueprint via `render.yaml` (Starter plan, persistent disk at /data).
The first-run admin password is baked in as a bcrypt hash only — change it in
Settings after first login, or override with the `PROJECTX_PASSWORD_HASH` env var.
