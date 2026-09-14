import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
from fastapi import FastAPI, Request
import uvicorn

# Настройки токена и вебхука для Render
TOKEN = "8952197475:AAG5cY8qVLGbu-59TuHZuVWtoKg4KzCwjsQ"
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
router = Router()

# Инициализируем бота и диспетчер глобально один раз
bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)

def get_schedule_keyboard(day_label: str = "Сегодня"):
    """Интерактивная клавиатура для календаря и расписания"""
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

@router.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Открыть календарь и расписание", callback_data="open_schedule")]
        ]
    )
    await message.answer(
        "⚡️ <b>TOPORIK HUB | Организатор</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Привет! Нажми кнопку ниже, чтобы открыть календарь:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@router.message(Command("schedule"))
@router.callback_query(F.data == "open_schedule")
async def show_schedule(event: Message | CallbackQuery):
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()

    text = (
        "📅 <b>Календарь и расписание</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "▫️ <b>День:</b> Сегодня\n"
        "▫️ <b>События / Пары:</b>\n"
        "  • 09:00 — Занятия / Встречи\n"
        "  • 12:00 — Свободное время\n\n"
        "<i>Используйте кнопки ниже для навигации:</i>"
    )

    if isinstance(event, CallbackQuery):
        await message.edit_text(text, reply_markup=get_schedule_keyboard("Сегодня"), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=get_schedule_keyboard("Сегодня"), parse_mode="HTML")

@router.callback_query(F.data.startswith("sched_"))
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
    
    await callback.message.edit_text(text, reply_markup=get_schedule_keyboard(day_text), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def back_to_main(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Открыть календарь и расписание", callback_data="open_schedule")]
        ]
    )
    await callback.message.edit_text("🏠 Вы вернулись в главное меню:", reply_markup=keyboard)
    await callback.answer()

# FastAPI приложение
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

@app.get("/")
async def index():
    return {"status": "Bot is running via Webhook!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
