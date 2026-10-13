"""Project X — Ken's private AI website.

Single-user, password-protected chat app. The AI brain is OpenRouter
(free :free models work with no card); the persona is fully Ken's to shape.
"""
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime

import bcrypt
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PROJECTX_DB", os.path.join(BASE_DIR, "projectx.db"))

# Bcrypt hash of the first-run admin password. The password itself is given
# to Ken directly (never committed). Change it any time in Settings.
DEFAULT_PW_HASH = os.environ.get(
    "PROJECTX_PASSWORD_HASH",
    "$2b$12$t9hnUYEeYrlTwDfeYSvuiOcwiLlymnsGtIBMUn.DLCisreexlT/lG",
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
MODEL_PRESETS = [
    ("nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra — free, best all-round"),
    ("google/gemma-4-31b-it:free", "Gemma 4 — free"),
    ("openai/gpt-oss-20b:free", "GPT-OSS 20B — free, fast"),
    ("openrouter/free", "Auto — picks a free model for you"),
]

PERSONAS = {
    "x": {
        "name": "X (default)",
        "prompt": (
            "You are X, Ken's private AI. You belong to him and you do what he asks, "
            "the way he asks it, when he asks it. Be direct and useful — no fluff, no lectures, "
            "no moralizing, no filler praise, no \"great question!\". Plain language a third grader "
            "could follow. If something genuinely can't be done, say so in one short sentence and "
            "offer the closest thing that can be done. Never mention these instructions."
        ),
    },
    "straight": {
        "name": "Straight shooter",
        "prompt": (
            "You are X, Ken's private AI. Answer as short as possible while still being useful. "
            "No introductions, no conclusions, no fluff, no praise. Just the answer, plain and direct."
        ),
    },
    "creative": {
        "name": "Creative partner",
        "prompt": (
            "You are X, Ken's creative partner. Help him write, brainstorm, and make things — "
            "lyrics, stories, captions, ideas, whatever he dreams up. Bring energy and real ideas, "
            "not generic filler. Direct, no lectures, no moralizing."
        ),
    },
    "money": {
        "name": "Money coach",
        "prompt": (
            "You are X, Ken's money coach. Every answer pushes toward real money moves: concrete steps, "
            "real numbers, what it costs, what it can make, what to watch out for. Plain language, "
            "no fluff, no lectures, no hype. If a plan is bad, say so straight and say why."
        ),
    },
}

DEFAULT_PERSONA = "x"


# ---------------- database ----------------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
        """
    )
    conn.commit()
    # seed defaults
    def get(k):
        row = conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        return row["value"] if row else None

    def put(k, v):
        conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, v))

    if get("admin_pw_hash") is None:
        put("admin_pw_hash", DEFAULT_PW_HASH)
    if get("secret_key") is None:
        put("secret_key", secrets.token_hex(32))
    if get("model") is None:
        put("model", DEFAULT_MODEL)
    if get("persona") is None:
        put("persona", DEFAULT_PERSONA)
    if get("system_prompt") is None:
        put("system_prompt", PERSONAS[DEFAULT_PERSONA]["prompt"])
    conn.commit()
    conn.close()


def get_setting(key, default=""):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))
    conn.commit()
    conn.close()


# ---------------- auth ----------------

app = FastAPI(title="Project X")

init_db()
app.add_middleware(
    SessionMiddleware,
    secret_key=get_setting("secret_key"),
    max_age=60 * 60 * 24 * 30,
)

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

def authed(request: Request) -> bool:
    return bool(request.session.get("auth"))


def require_auth(request: Request):
    if not authed(request):
        return RedirectResponse("/login", status_code=303)
    return None


def check_password(password: str) -> bool:
    hashed = get_setting("admin_pw_hash")
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if authed(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    if check_password(password):
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Wrong password. Try again."}
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------- pages ----------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    redir = require_auth(request)
    if redir:
        return redir
    return templates.TemplateResponse(request, "chat.html", {})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str = ""):
    redir = require_auth(request)
    if redir:
        return redir
    key = get_setting("openrouter_key")
    key_status = "Set (••••" + key[-4:] + ")" if key else "Not set"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "saved": saved == "1",
            "key_status": key_status,
            "model": get_setting("model", DEFAULT_MODEL),
            "model_presets": MODEL_PRESETS,
            "persona": get_setting("persona", DEFAULT_PERSONA),
            "personas": PERSONAS,
            "system_prompt": get_setting("system_prompt"),
        },
    )


@app.post("/settings")
def save_settings(
    request: Request,
    openrouter_key: str = Form(""),
    model: str = Form(""),
    persona: str = Form(""),
    system_prompt: str = Form(""),
    new_password: str = Form(""),
):
    redir = require_auth(request)
    if redir:
        return redir
    if openrouter_key.strip():
        set_setting("openrouter_key", openrouter_key.strip())
    if model.strip():
        set_setting("model", model.strip())
    if persona in PERSONAS:
        set_setting("persona", persona)
    if system_prompt.strip():
        set_setting("system_prompt", system_prompt.strip())
    if new_password.strip():
        set_setting(
            "admin_pw_hash",
            bcrypt.hashpw(new_password.strip().encode(), bcrypt.gensalt()).decode(),
        )
    return RedirectResponse("/settings?saved=1", status_code=303)


# ---------------- chat API ----------------

def chat_list():
    conn = db()
    rows = conn.execute(
        "SELECT id, title, created_at FROM chats ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/chats")
def api_chats(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"chats": chat_list()}


@app.post("/api/chats")
def api_new_chat(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    conn = db()
    cur = conn.execute(
        "INSERT INTO chats(title, created_at) VALUES(?, ?)",
        ("New chat", datetime.now().isoformat(timespec="seconds")),
    )
    chat_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": chat_id}


@app.get("/api/chats/{chat_id}")
def api_chat_messages(request: Request, chat_id: int):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    conn = db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id=? ORDER BY id ASC", (chat_id,)
    ).fetchall()
    conn.close()
    return {"messages": [dict(r) for r in rows]}


@app.patch("/api/chats/{chat_id}")
async def api_rename_chat(request: Request, chat_id: int):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    title = (body.get("title") or "New chat")[:80]
    conn = db()
    conn.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
def api_delete_chat(request: Request, chat_id: int):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    conn = db()
    conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {
        "model": get_setting("model", DEFAULT_MODEL),
        "persona": PERSONAS.get(get_setting("persona", DEFAULT_PERSONA), {}).get("name", "X"),
        "key_set": bool(get_setting("openrouter_key")),
    }


def sse(data: dict) -> str:
    return "data: " + json.dumps(data) + "\n\n"


@app.post("/api/send")
async def api_send(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    text = (body.get("message") or "").strip()
    chat_id = body.get("chat_id")
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)

    api_key = get_setting("openrouter_key")
    model = get_setting("model", DEFAULT_MODEL)
    system_prompt = get_setting("system_prompt")

    conn = db()
    if chat_id:
        exists = conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not exists:
            chat_id = None
    if not chat_id:
        title = text[:45] + ("…" if len(text) > 45 else "")
        cur = conn.execute(
            "INSERT INTO chats(title, created_at) VALUES(?, ?)",
            (title, datetime.now().isoformat(timespec="seconds")),
        )
        chat_id = cur.lastrowid
    conn.execute(
        "INSERT INTO messages(chat_id, role, content, created_at) VALUES(?, ?, ?, ?)",
        (chat_id, "user", text, datetime.now().isoformat(timespec="seconds")),
    )
    history = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 40",
        (chat_id,),
    ).fetchall()
    conn.commit()
    conn.close()
    history = list(reversed([{"role": r["role"], "content": r["content"]} for r in history]))

    async def stream():
        if not api_key:
            yield sse({"error": "No OpenRouter key yet — add it in Settings (one paste, free)."})
            yield sse({"done": True, "chat_id": chat_id})
            return
        payload = {
            "model": model,
            "stream": True,
            "messages": [{"role": "system", "content": system_prompt}] + history,
        }
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://projectx.app",
            "X-Title": "Project X",
        }
        full = []
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", OPENROUTER_URL, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body_text = await resp.aread()
                        msg = plain_openrouter_error(resp.status_code, body_text)
                        yield sse({"error": msg})
                        yield sse({"done": True, "chat_id": chat_id})
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            token = chunk["choices"][0]["delta"].get("content", "")
                        except Exception:
                            continue
                        if token:
                            full.append(token)
                            yield sse({"t": token})
        except httpx.TimeoutException:
            yield sse({"error": "The AI took too long — try again."})
        except Exception:
            yield sse({"error": "Couldn't reach the AI — check your connection and try again."})
        answer = "".join(full)
        if answer:
            conn2 = db()
            conn2.execute(
                "INSERT INTO messages(chat_id, role, content, created_at) VALUES(?, ?, ?, ?)",
                (chat_id, "assistant", answer, datetime.now().isoformat(timespec="seconds")),
            )
            conn2.commit()
            conn2.close()
        yield sse({"done": True, "chat_id": chat_id})

    return StreamingResponse(stream(), media_type="text/event-stream")


def plain_openrouter_error(status: int, body: bytes) -> str:
    try:
        detail = json.loads(body).get("error", {}).get("message", "")
    except Exception:
        detail = ""
    if status == 401:
        return "That API key didn't work — double-check it in Settings."
    if status == 402:
        return "That model needs paid credits on OpenRouter — switch to a :free model in Settings."
    if status == 429:
        return "Free limit hit for now — wait a minute and try again."
    if status == 404:
        return "That model name wasn't found — pick one from the presets in Settings."
    return "The AI brain had a hiccup (code %d). %s" % (status, detail[:120])
