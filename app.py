import os
import sqlite3
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

# --- Настройка Gemini ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Используем актуальную модель (как просит Google в ошибке)
model = genai.GenerativeModel("gemini-3.8-flash")

# --- База данных ---
def init_db():
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY, name TEXT, scene INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, role TEXT, content TEXT)""")
    conn.commit()
    conn.close()

init_db()

# --- Сцены ---
SCENES = {
    1: {
        "title": "Утро дома",
        "next_button": "Выйти из дома →",
        "next_scene": 2,
        "start_prompt": "Ты мама Клэр и папа Марк. Главный герой только что проснулся и зашел на кухню. Поприветствуй его коротко, как родители (например, 'Доброе утро, соня. Будешь завтракать?'). Без смайликов.",
        "prompt": """Ты — сцена из истории. Сейчас утро, герой дома. На кухне мама Клэр и папа Марк.
Они обычные родители. Говорят коротко, без смайликов. Не знают про лес и пропажи.
Формат ответа:
Клэр: текст
Марк: текст
(1-2 реплики за раз, коротко.)"""
    },
    2: {
        "title": "Школа",
        "next_button": "После школы →",
        "next_scene": 3,
        "start_prompt": "Ты Эмили, Джейк и Тайлер. Вы встретили главного героя в школьном коридоре на перемене. Напиши короткое приветствие от лица Эмили и Джейка. Без смайликов.",
        "prompt": """Ты — сцена в школе. Герой в коридоре на перемене. Друзья: Эмили, Джейк, Тайлер.
Эмили добрая. Джейк саркастичный. Тайлер шутит (пишет 'ахаха').
Они НЕ знают про лес. Без смайликов.
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст
(1-2 реплики за раз, коротко.)"""
    },
    3: {
        "title": "После школы",
        "next_button": None,
        "next_scene": None,
        "start_prompt": "Ты Эмили, Джейк и Тайлер. Вы вышли из школы и обсуждаете пропажи в городе. Начни разговор с короткой фразы от Джейка. Без смайликов.",
        "prompt": """Ты — сцена после школы. Герой с друзьями.
Они обсуждают пропажи. Без смайликов, коротко.
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст
(1-2 реплики за раз.)"""
    }
}

# --- Модели данных ---
class EnterName(BaseModel):
    user_id: str
    name: str

class SendMessage(BaseModel):
    user_id: str
    text: str

class NextScene(BaseModel):
    user_id: str

# --- API ---
@app.post("/api/enter")
def enter(data: EnterName):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, name, scene) VALUES (?, ?, 1)", (data.user_id, data.name))
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

    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (data.user_id, "user", data.text))
    conn.commit()

    c.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 15", (data.user_id,))
    history = list(reversed(c.fetchall()))
    conn.close()

    prompt = SCENES[scene]["prompt"]
    hist_text = "\n".join([f"{'Ты' if r=='user' else 'Персонажи'}: {t}" for r, t in history])

    full_prompt = f"""{prompt}

Твоё имя (героя): {name}

История переписки:
{hist_text}

Ответь на последнее сообщение героя. Только реплики персонажей, коротко."""

    try:
        resp = model.generate_content(full_prompt)
        ai_text = resp.text.strip()
    except Exception as e:
        ai_text = f"Ошибка ИИ: {str(e)}"

    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (data.user_id, "assistant", ai_text))
    conn.commit()
    conn.close()
    return {"reply": ai_text}

@app.post("/api/next")
def next_scene(data: NextScene):
    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("SELECT name, scene FROM users WHERE user_id=?", (data.user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"error": "not found"}
    name, scene = row

    nxt = SCENES[scene]["next_scene"]
    if not nxt:
        conn.close()
        return {"error": "no next scene"}

    c.execute("UPDATE users SET scene=? WHERE user_id=?", (nxt, data.user_id))
    c.execute("DELETE FROM messages WHERE user_id=?", (data.user_id,)) 
    conn.commit()

    start_prompt = SCENES[nxt]["start_prompt"]
    full_prompt = f"{start_prompt}\n\nИмя героя: {name}\n\nНапиши первое сообщение от лица персонажей. Формат: Имя: текст"
    
    try:
        resp = model.generate_content(full_prompt)
        ai_text = resp.text.strip()
    except Exception as e:
        ai_text = f"Ошибка ИИ: {str(e)}"

    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (data.user_id, "assistant", ai_text))
    conn.commit()
    conn.close()
    
    return {"scene": nxt, "title": SCENES[nxt]["title"], "next_button": SCENES[nxt]["next_button"], "start_message": ai_text}

# --- Раздача файлов ---
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
