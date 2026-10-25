import os
import sqlite3
import google.generativeai as genai
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
generation_config = {
    "temperature": 0.9,
    "max_output_tokens": 150,
}
model = genai.GenerativeModel("gemini-2.5-flash-lite", generation_config=generation_config)

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

SCENES = {
    1: {
        "title": "Утро дома",
        "bg": "09d4431cba340026e9141a3e68b9028a.jpg",
        "start_msg": "Автор: Ты просыпаешься от запаха блинчиков. На кухне уже гремит посудой мама, а папа читает новости.",
        "prompt": """Ты — сцена из жуткой истории. Сейчас утро, герой завтракает на кухне.
Мама (Клэр) и Папа (Марк) очень любящие и хорошо относятся к герою. В репликах пиши спикера как 'Мама:' или 'Папа:', но в тексте они общаются как живые люди и называют друг друга по именам.
Они не знают про лес.
Если герой говорит, что закончил завтракать, собирается в школу или прощается — 
в самом конце своего ответа добавь секретный тег [NEXT_SCENE].
Используй действия в скобках.
Формат:
Мама: текст
Папа: текст"""
    },
    2: {
        "title": "Школа",
        "bg": "9dd61606db7e23940039107aa62f645c.jpg",
        "start_msg": "Автор: Ты заходишь в школу. Ты здесь новенькая. В коридорах шумно, но твои друзья уже ждут тебя у кабинета.",
        "prompt": """Ты — сцена в школе (жуткий детектив). Перемена. Герой (новенькая) встретил друзей.
Эмили — добрая, милая, тепло общается. Не использует смайлики. Её подбешивает Тайлер с его тупыми шутками.
Джейк — саркастичный, грубый, очень смелый, красивый. Сначала он холоден с новенькой (героем), может грубить, но в глубине души начинает проникаться. Он груб только с идиотами.
Тайлер — угарный, постоянно ржет как "ХХПХАЭАХАХААХЭА", подкалывает всех, тупые шутки.
Они НЕ знают про лес. Обсуждают пропажи в городе.
Если герой предлагает пойти искать пропавших или уйти из школы — 
в конце ответа добавь [NEXT_SCENE].
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст"""
    },
    3: {
        "title": "После школы",
        "bg": "2ff49648937cf5ecd2639bd0b8c0ffd4.jpg",
        "start_msg": "Автор: Уроки закончились. Вы выходите на улицу, где моросит мелкий дождь. Пора решать, что делать дальше.",
        "prompt": """Ты — сцена после школы (жуткий детектив). Вы с друзьями вышли на улицу.
Обсуждаете пропажи, строите теории. 
Джейк начинает относиться к герою чуть теплее. Эмили переживает. Тайлер шутит.
Если герой предлагает пойти в лес — 
в конце ответа добавь [NEXT_SCENE].
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст"""
    },
    4: {
        "title": "Рыжий лес",
        "bg": "file_00000000a07c8246a267b80e9bc86a53.png",
        "start_msg": "Автор: Вы заходите в лес. Деревья здесь странного рыжеватого оттенка. Ветер стих, и стало подозрительно тихо.",
        "prompt": """Ты — сцена в жутком Рыжем лесу.
Вокруг туман. Друзья напуганы. 
Эмили шепчет от страха. Джейк пытается шутить, чтобы скрыть страх, но он защищает героя. Тайлер молчит (что странно для него).
В какой-то момент вдалеке должен мелькнуть силуэт (намек на духа).
Формат:
Эмили: текст
Джейк: текст
Тайлер: текст"""
    }
}

class EnterName(BaseModel):
    user_id: str
    name: str

class SendMessage(BaseModel):
    user_id: str
    text: str

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
    
    return {
        "name": name, 
        "scene": scene, 
        "title": SCENES[scene]["title"], 
        "bg": SCENES[scene]["bg"],
        "messages": msgs
    }

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

    c.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 10", (data.user_id,))
    history = list(reversed(c.fetchall()))
    conn.close()

    prompt = SCENES[scene]["prompt"]
    hist_text = "\n".join([f"{'Ты' if r=='user' else 'Персонажи'}: {t}" for r, t in history])

    full_prompt = f"""{prompt}

Твоё имя (героя): {name}

История переписки:
{hist_text}

Ответь на последнее сообщение героя. Если сцена должна смениться, не забудь добавить [NEXT_SCENE] в конце."""

    try:
        resp = model.generate_content(full_prompt)
        ai_text = resp.text.strip()
    except Exception as e:
        ai_text = f"Ошибка ИИ: {str(e)}"

    next_scene = None
    new_bg = None
    start_msg = None
    
    if "[NEXT_SCENE]" in ai_text:
        next_scene = scene + 1
        ai_text = ai_text.replace("[NEXT_SCENE]", "").strip()
        
        if next_scene in SCENES:
            new_bg = SCENES[next_scene]["bg"]
            start_msg = SCENES[next_scene]["start_msg"]
            
            c = conn = sqlite3.connect("story.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET scene=? WHERE user_id=?", (next_scene, data.user_id))
            cursor.execute("DELETE FROM messages WHERE user_id=?", (data.user_id,))
            conn.commit()
            conn.close()
            
            c = conn = sqlite3.connect("story.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (data.user_id, "author", start_msg))
            conn.commit()
            conn.close()

    conn = sqlite3.connect("story.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (data.user_id, "assistant", ai_text))
    conn.commit()
    conn.close()
    
    return {"reply": ai_text, "next_scene": next_scene, "new_bg": new_bg, "start_msg": start_msg}

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
