from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram_service import send_telegram_message

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BookmarkRequest(BaseModel):
    date: str
    time: str
    send_date: str
    priority: str
    text: str
    file_url: str = None

@app.get("/")
def health_check():
    return {"status": "active", "message": "Advanced Calendar Bot Backend is running!"}

@app.post("/api/send-bookmark")
def create_bookmark(data: BookmarkRequest):
    try:
        result = send_telegram_message(
            date=data.date,
            time=data.time,
            send_date=data.send_date,
            priority=data.priority,
            text=data.text,
            file_url=data.file_url
        )
        
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=f"Telegram error: {result.get('description')}")
            
        return {"success": True, "message": "Заметка успешно отправлена!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
