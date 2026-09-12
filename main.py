import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8916954883:AAHZoGA8i2367ZdnJ0zOGXNS0svjgKWAiwE")
CHAT_ID = os.getenv("CHAT_ID", "8870678654")

@app.get("/")
def health_check():
    return {"status": "active", "message": "Calendar Bot Backend is running!"}

@app.post("/api/send-bookmark")
async def create_bookmark(
    date: str = Form(...),
    time: str = Form(...),
    send_date: str = Form(...),
    priority: str = Form(...),
    text: str = Form(...),
    file: UploadFile = File(None)
):
    priority_map = {
        "high": "🔴 Красный (Высокая)",
        "medium": "🟠 Оранжевый (Средняя)",
        "low": "🟢 Зеленый (Низкая)"
    }
    p_text = priority_map.get(priority, "⚪ Обычная")

    message = (
        f"📌 **Новая закладка из календаря**\n\n"
        f"📅 **Дата события:** {date}\n"
        f"🚀 **Дата отправки боту:** {send_date} в {time}\n"
        f"⚡ **Важность:** {p_text}\n\n"
        f"💬 **Текст:**\n{text}"
    )

    try:
        if file:
            file_bytes = await file.read()
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            files = {"document": (file.filename, file_bytes)}
            data = {"chat_id": CHAT_ID, "caption": message, "parse_mode": "Markdown"}
            
            response = requests.post(url, data=data, files=files)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
            
            response = requests.post(url, json=payload)

        result = response.json()
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=f"Telegram error: {result.get('description')}")
            
        return {"success": True, "message": "Заметка успешно отправлена!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
