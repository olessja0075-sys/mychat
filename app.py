import os
import json
import sqlite3
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")

# ---------- База ----------
def init_db():
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT,
        scene INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        role TEXT,
        content TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# ---------- Сцены ----------
SCENES = {
    1: {
        "title": "Утро дома",
        "characters": "Клэр (мама, добрая но уставшая), Марк (папа, спокойный, немногословный)",
        "prompt": """Ты — сцена из истории. Сейчас утро, главный герой проснулся дома. На кухне мама Клэр и папа Марк.
Клэр и Марк — обычные родители. Говорят коротко, по-житейски, без смайликов и без эмодзи.
Они не знают ничего про лес и пропажи. Обсуждают обычные дела: завтрак, школу, планы.
Главный герой может спросить что угодно — отвечай как живые люди, короткими фразами.
Если герой говорит что-то странное — удивись, переспроси, но не выходи из роли.
НИКОГДА не признавайся, что ты ИИ. Пиши только реплики персонажей в формате:
Клэр: текст
Марк: текст
(Один или два персонажа за раз, коротко.)""",
        "next_button": "Выйти из дома →",
        "next_scene": 2
    },
    2: {
        "title": "Школа",
        "characters": "Эмили (милая, добрая), Джейк (саркастичный, крутой), Тайлер (угарный, чуть туповат), мисс Харпер (строгая училка)",
        "prompt": """Ты — сцена в школе. Главный герой в коридоре на перемене. Рядом друзья: Эмили, Джейк, Тайлер.
Эмили добрая, говорит мягко, коротко. Джейк саркастичный, язвит, но заботится. Тайлер шутит, иногда не в тему, пишет с "ахаха" и скобками.
Через несколько сообщений появляется мисс Харпер — строгая, сухая, не любит опозданий и шума.
Они НЕ знают про лес и пропажи. Обсуждают школу, слухи, странности.
Без смайликов и эмодзи (кроме Тайлера — у него "ахаха" и "))").
Формат ответа:
Эмили: текст
Джейк: текст
Тайлер: текст
Мисс Харпер: текст
(1-2 персонажа за раз, коротко.)""",
        "next_button": "После школы →",
        "next_scene": 3
    },
    3: {
        "title": "После школы",
        "characters": "Эмили, Джейк, Тайлер",
        "prompt": """Ты — сцена после школы. Главный герой с друзьями (Эмили, Джейк, Тайлер) решает, что делать.
Они обсуждают пропажи в городе. Пока не знают про лес. Могут строить догадки, спорить.
Без смайликов. Короткие фразы.
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст
(1-2 персонажа за раз.)""",
        "next_button": None,
        "next_scene": None
    }
}

# ---------- Модели ----------
class EnterName(BaseModel):
    user_id: str
    name: str

class SendMessage(BaseModel):
    user_id: str
    text: str

class NextScene(BaseModel):
    user_id: str

# ---------- API ----------
@app.post("/api/enter")
def enter(data: EnterName):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, name, scene) VALUES (?, ?, 1)",
              (data.user_id, data.name))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/story/{user_id}")
def get_story(user_id: str):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("SELECT name, scene FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not found"}
    name, scene = row
    c.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id", (user_id,))
    msgs = [{"role": r, "content": t} for r, t in c.fetchall()]
    conn.close()
    return {"name": name, "scene": scene, "title": SCENES[scene]["title"],
            "next_button": SCENES[scene]["next_button"], "messages": msgs}

@app.post("/api/send")
def send(data: SendMessage):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("SELECT name, scene FROM users WHERE user_id=?", (data.user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not found"}
    name, scene = row

    # сохранить сообщение пользователя
    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
              (data.user_id, "user", data.text))
    conn.commit()

    # история для контекста
    c.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 20",
              (data.user_id,))
    history = list(reversed(c.fetchall()))
    conn.close()

    prompt = SCENES[scene]["prompt"]
    hist_text = "\n".join([f"{'Ты' if r=='user' else 'Персонажи'}: {t}" for r, t in history])

    full_prompt = f"""{prompt}

Твоё имя (главного героя): {name}

История переписки:
{hist_text}

Теперь ответь на последнее сообщение главного героя. Только реплики персонажей, коротко."""

    try:
        resp = model.generate_content(full_prompt)
        ai_text = resp.text.strip()
    except Exception as e:
        ai_text = f"Ошибка ИИ: {str(e)}"

    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
              (data.user_id, "assistant", ai_text))
    conn.commit()
    conn.close()

    return {"reply": ai_text}

@app.post("/api/next")
def next_scene(data: NextScene):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("SELECT scene FROM users WHERE user_id=?", (data.user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not found"}
    scene = row[0]
    nxt = SCENES[scene]["next_scene"]
    if nxt:
        c.execute("UPDATE users SET scene=? WHERE user_id=?", (nxt, data.user_id))
        conn.commit()
        scene = nxt
    conn.close()
    return {"scene": scene, "title": SCENES[scene]["title"],
            "next_button": SCENES[scene]["next_button"]}

# ---------- Статика ----------
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
