from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Прямо здесь укажи твой новый токен и ID
BOT_TOKEN = "8916954883:AAHZoGA8i2367ZdnJ0zOGXNS0svjgKWAiwE"
CHAT_ID = "8870678654"


class BookmarkRequest(BaseModel):
  date: str
  time: str
  text: str


@app.get("/")
def health_check():
  return {"status": "active", "message": "Calendar bot backend is running!"}


@app.post("/api/send-bookmark")
def send_bookmark(data: BookmarkRequest):
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
