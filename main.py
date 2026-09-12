from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI()

# Разрешаем CORS для запросов с твоего фронтенда на Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене можно заменить на URL твоего сайта на Vercel
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BOT_TOKEN = "8874357037:AAHu8dEk97Mb9NT9MCfpEPCpDj7z6NQnKRo"
CHAT_ID = "8870678654"


class BookmarkRequest(BaseModel):
  date: str  # Формат YYYY-MM-DD
  time: str  # Формат HH:MM
  text: str


@app.get("/")
def health_check():
  return {"status": "active", "message": "Calendar bot backend is running!"}


@app.post("/api/send-bookmark")
def send_bookmark(data: BookmarkRequest):
  # Формируем красивое сообщение для Telegram
  message = (
      f"📌 **Новая закладка из календаря**\n\n"
      f"📅 **Дата:** {data.date}\n"
      f"⏰ **Время отправки:** {data.time}\n\n"
      f"💬 **Текст:**\n{data.text}"
  )

  url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
  payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}

  try:
    response = requests.post(url, json=payload)
    response_data = response.json()

    if not response_data.get("ok"):
      raise HTTPException(
          status_code=400,
          detail=f"Telegram API Error: {response_data.get('description')}",
      )

    return {"success": True, "message": "Закладка успешно отправлена в бот!"}
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Failed to send message: {str(e)}"
    )