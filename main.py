import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.exceptions import TelegramBadRequest
from fastapi import FastAPI, Request
from pydantic import BaseModel
import typing
import uvicorn

TOKEN = "8916954883:AAHZoGA8i2367ZdnJ0zOGXNS0svjgKWAiwE"

WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://botkalendar.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Глобальная переменная для сохранения твоего Telegram ID
USER_CHAT_ID = None

class SiteNote(BaseModel):
    message: str
    title: typing.Optional[str] = "Новая заметка из календаря"

def get_schedule_keyboard(day_label: str = "Сегодня"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️ Вчера", callback_data="sched_prev"),
                InlineKeyboardButton(text=f"📌 {day_label}", callback_data="sched_current"),
                InlineKeyboardButton(text="Завтра ▶️", callback_data="sched_next"),
            ],
            [
                InlineKeyboardButton(text="📝 Добавить событие", callback_data="sched_add"),
                InlineKeyboardButton(text="📋 Список задач", callback_data="sched_list"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
            ]
        ]
    )

@dp.message(Command("start"))
async def cmd_start(message: Message):
    global USER_CHAT_ID
    USER_CHAT_ID = message.from_user.id  # Автоматически сохраняем твой ID!
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Открыть календарь и расписание", callback_data="open_schedule")]
        ]
    )
    await message.answer(
        f"📅 <b>Календарь-бот подключен!</b>\n"
        f"Ваш Telegram ID сохранен: <code>{USER_CHAT_ID}</code>\n\n"
        "Нажми кнопку ниже, чтобы открыть расписание:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.message(Command("schedule"))
@dp.callback_query(F.data == "open_schedule")
async def show_schedule(event: Message | CallbackQuery):
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()

    text = (
        "📅 <b>Календарь и расписание</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "▫️ <b>День:</b> Сегодня\n"
        "▫️ <b>События / Пары:</b>\n"
        "  • 09:00 — Занятия\n"
        "  • 12:00 — Обед / Свободно\n\n"
        "<i>Используйте кнопки ниже для навигации:</i>"
    )

    keyboard = get_schedule_keyboard("Сегодня")
    if isinstance(event, CallbackQuery):
        try:
            await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except TelegramBadRequest:
            pass
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("sched_"))
async def process_schedule_callbacks(callback: CallbackQuery):
    action = callback.data.split("_")[1]
    
    if action == "prev":
        day_text = "Вчера"
    elif action == "next":
        day_text = "Завтра"
    elif action == "add":
        await callback.answer("Функция добавления события в разработке", show_alert=True)
        return
    elif action == "list":
        await callback.answer("Список всех задач пуст", show_alert=True)
        return
    else:
        day_text = "Сегодня"

    text = (
        f"📅 <b>Календарь и расписание ({day_text})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"▫️ <b>Состояние:</b> Просмотр на день ({day_text})\n"
        "▫️ <b>События:</b>\n"
        "  • Данные успешно обновлены\n\n"
        "<i>Используйте кнопки ниже для навигации:</i>"
    )
    
    keyboard = get_schedule_keyboard(day_text)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        pass
        
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Открыть календарь и расписание", callback_data="open_schedule")]
        ]
    )
    try:
        await callback.message.edit_text("🏠 Вы вернулись в главное меню:", reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    await callback.answer()

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logging.info(f"Вебхук успешно установлен: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"Ошибка установки вебхука: {e}")

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    update_data = await request.json()
    update = Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}

# Эндпоинт, куда сайт отправляет заметки
@app.post("/api/send-from-site")
async def send_from_site(data: SiteNote):
    global USER_CHAT_ID
    if not USER_CHAT_ID:
        return {"status": "error", "detail": "Bot has no chat_id. Send /start to the bot first!"}
    
    try:
        text = f"📌 <b>Заметка из календаря (сайт):</b>\n\n{data.message}"
        await bot.send_message(chat_id=USER_CHAT_ID, text=text, parse_mode="HTML")
        return {"status": "success", "detail": "Note sent to Telegram"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/")
async def index():
    return {"status": "Calendar Bot is running!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
