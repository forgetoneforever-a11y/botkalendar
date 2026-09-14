import asyncio
import logging
import os
import random
import re
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    FSInputFile,
)
from fastapi import FastAPI, Request
import uvicorn
import yt_dlp

# НАСТРОЙКИ БОТА И АДМИНЫ
TOKEN = "8952197475:AAG5cY8qVLGbu-59TuHZuVWtoKg4KzCwjsQ"
ADMIN_IDS = [1320294475, 5619340928, 8870678654]
BOT_USERNAME = "toporik18_bot"

WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)
router = Router()
HEAVY_WORK_MODE = False

# Инициализация базы данных SQLite
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode = WAL;")
conn.execute("PRAGMA synchronous = NORMAL;")
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    repeat_mode INTEGER DEFAULT 1,
    language TEXT DEFAULT 'ru'
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,
    caption TEXT,
    category TEXT DEFAULT 'kids'
)
"""
)

# Обновленная таблица заметок (добавлен флаг is_sent, чтобы не отправлять повторно)
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    note_text TEXT,
    note_datetime TEXT,
    media_file_id TEXT,
    media_type TEXT,
    is_sent INTEGER DEFAULT 0
)
"""
)

# Таблица для шпаргалок / базы знаний
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS cheat_sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,
    title TEXT,
    content TEXT
)
"""
)

# Заполним базу начальными шпаргалками, если она пустая
cursor.execute("SELECT COUNT(*) FROM cheat_sheets")
if cursor.fetchone()[0] == 0:
    sample_cheats = [
        ("code", "Python: Основы и списки", "<b>Срезы:</b> `text[::-1]` (разворот строки)\n<b>Генераторы:</b> `[x**2 for x in range(10)]`"),
        ("code", "JavaScript: Асинхронность", "Используй `async/await` вместо цепочек `.then()`. Для запросов лучше применять встроенный `fetch()`."),
        ("mods", "Minecraft Fabric (Сервер)", "Обязательные моды для оптимизации: **Lithium**, **FerriteCore**, **Krypton**."),
        ("mods", "Dota 2: Консольные команды", "Показать FPS и пинг: `dota_render_fps 1`\nБыстрый выбор юнита: зажми `Ctrl` + клик."),
        ("study", "Технология машиностроения", "Основные этапы разработки ТП: анализ чертежа, выбор метода получения заготовки, расчет припусков и режимов резания.")
    ]
    cursor.executemany("INSERT INTO cheat_sheets (category, title, content) VALUES (?, ?, ?)", sample_cheats)
    conn.commit()

# Безопасное добавление колонок, если таблица уже существовала старая
for col_def, table_name in [
    (("language", "TEXT DEFAULT 'ru'"), "users"),
    (("caption", "TEXT"), "videos"),
    (("category", "TEXT DEFAULT 'kids'"), "videos"),
    (("is_sent", "INTEGER DEFAULT 0"), "notes"),
]:
    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_def[0]} {col_def[1]}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS user_history (
    user_id INTEGER,
    video_id INTEGER,
    PRIMARY KEY (user_id, video_id)
)
"""
)
cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_lang ON users(language);")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id);")
conn.commit()


# Состояния FSM
class AdminStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_video = State()
    waiting_for_caption = State()


class UserStates(StatesGroup):
    waiting_for_report = State()


class NoteStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_datetime = State()
    waiting_for_media = State()


# Тексты интерфейса (в стиле Glass / Neon)
LANG_TEXTS = {
    "ru": {
        "welcome": (
            "⚡️ <b>TOPORIK HUB | Главное меню</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔮 <i>Добро пожаловать в персональный хаб! Выберите нужный раздел ниже:</i>"
        ),
        "choose_lang": "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        "lang_changed": "✅ Язык успешно изменен на русский!",
        "btn_random": "⚡️ Случайное видео",
        "btn_kids": "🧸 Категория: Kids",
        "btn_porno": "🔥 Категория: Porno",
        "btn_note": "📝 Создать заметку",
        "btn_cheats": "📚 База знаний / Шпоры",
        "btn_help": "🆘 Справка",
        "btn_contact": "💬 Связь с админом",
        "btn_admin": "🛠 Админ-панель",
        "help_text": (
            "📌 <b>Справочник по возможностям бота:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• 🔗 <b>Скачивание:</b> просто отправь ссылку (YouTube, TikTok и др.)\n"
            "• 📝 <b>Умные заметки:</b> нажми «Создать заметку», напиши текст, задай дату/время в формате <code>ДД.ММ.ГГГГ ЧЧ:ММ</code> (например, <i>15.09.2026 14:30</i>), и бот пришлет её точно в срок!\n"
            "• 📚 <b>Шпаргалки:</b> учебные материалы, код, команды по играм\n"
            "• ⚙️ <b>Настройки:</b> управление историей и повторами видео\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 В выбранной категории пока нет ни одного видеоматериала!",
        "video_deleted_warn": "💡 <b>Совет:</b> рекомендуем пересылать понравившиеся ролики в «Избранное», так как это сообщение автоматически удалится через 25 секунд!",
    }
}


def get_user_lang(user_id: int) -> str:
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] in LANG_TEXTS:
        return row[0]
    return "ru"


def get_language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
            ],
            [
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk"),
                InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="set_lang_kk"),
            ],
        ]
    )


def get_user_keyboard(is_admin: bool, lang: str = "ru"):
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    keyboard = [
        [
            InlineKeyboardButton(text=t["btn_kids"], callback_data="watch_kids"),
            InlineKeyboardButton(text=t["btn_porno"], callback_data="watch_porno"),
        ],
        [InlineKeyboardButton(text=t["btn_random"], callback_data="random_video")],
        [
            InlineKeyboardButton(text=t["btn_note"], callback_data="start_note"),
            InlineKeyboardButton(text=t["btn_cheats"], callback_data="open_cheats"),
        ],
        [
            InlineKeyboardButton(text=t["btn_help"], callback_data="help_menu"),
            InlineKeyboardButton(text=t["btn_contact"], callback_data="contact_admin"),
        ],
        [InlineKeyboardButton(text="🌍 Сменить язык / Language", callback_data="change_language")],
    ]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Загрузить новое видео", callback_data="add_video")],
            [InlineKeyboardButton(text="🗑 Управление базой видео", callback_data="manage_videos_0")],
            [InlineKeyboardButton(text="📊 Статистика бота", callback_data="stats")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")],
        ]
    )


# ==========================================
# ФОНОВЫЙ ПЛАНИРОВЩИК ЗАМЕТОК
# ==========================================
async def notes_scheduler(bot: Bot):
    """Каждую минуту проверяет базу данных на наличие наступивших заметок."""
    while True:
        try:
            now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            
            # Выбираем неудаленные заметки, у которых время меньше или равно текущему
            cursor.execute(
                "SELECT id, user_id, note_text, media_file_id, media_type, note_datetime FROM notes WHERE is_sent = 0"
            )
            notes = cursor.fetchall()

            for note_id, user_id, note_text, media_file_id, media_type, note_datetime in notes:
                # Пытаемся распарсить дату из заметки
                try:
                    # Приводим к единому формату сравнения строк или объектов datetime
                    clean_note_dt = note_datetime.replace(" в ", " ").strip()
                    # Поддерживаем варианты разделителей
                    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y-%H:%M"):
                        try:
                            parsed_dt = datetime.strptime(clean_note_dt, fmt)
                            break
                        except ValueError:
                            parsed_dt = None
                    
                    # Если распарсили успешно, сравниваем с текущим временем (с точностью до минуты)
                    if parsed_dt and datetime.now() >= parsed_dt:
                        # Помечаем заметку как отправленную
                        cursor.execute("UPDATE notes SET is_sent = 1 WHERE id = ?", (note_id,))
                        conn.commit()

                        text_to_send = (
                            f"⏰ <b>Напоминание по заметке!</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📌 {note_text}"
                        )

                        lang = get_user_lang(user_id)
                        is_adm = user_id in ADMIN_IDS
                        kb = get_user_keyboard(is_adm, lang)

                        if media_file_id:
                            if media_type == "photo":
                                await bot.send_photo(chat_id=user_id, photo=media_file_id, caption=text_to_send, reply_markup=kb, parse_mode="HTML")
                            elif media_type == "video":
                                await bot.send_video(chat_id=user_id, video=media_file_id, caption=text_to_send, reply_markup=kb, parse_mode="HTML")
                            else:
                                await bot.send_document(chat_id=user_id, document=media_file_id, caption=text_to_send, reply_markup=kb, parse_mode="HTML")
                        else:
                            await bot.send_message(chat_id=user_id, text=text_to_send, reply_markup=kb, parse_mode="HTML")
                except Exception as ex:
                    logging.error(f"Ошибка при обработке конкретной заметки ID {note_id}: {ex}")

        except Exception as e:
            logging.error(f"Ошибка в планировщике заметок: {e}")
        
        await asyncio.sleep(60)  дверь каждую минуту


# ==========================================
# ФУНКЦИЯ 1: СКАЧИВАНИЕ ВИДЕО/МУЗЫКИ ПО ССЫЛКЕ (yt-dlp)
# ==========================================
@router.message(F.text.regexp(r"https?://[^\s]+"))
async def download_media_link(message: Message):
    url = message.text.strip()
    
    if len(url.split()) > 1 or url.startswith("/"):
        return

    processing_msg = await message.answer("⏳ <b>Скачиваю медиа по ссылке...</b> Пожалуйста, подождите.", parse_mode="HTML")
    
    output_template = f"downloads/media_{message.from_user.id}_%(id)s.%(ext)s"
    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_template,
        'max_filesize': 50 * 1024 * 1024,
        'noplaylist': True,
    }

    downloaded_file = None
    try:
        def run_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        downloaded_file = await asyncio.to_thread(run_dl)

        if downloaded_file and os.path.exists(downloaded_file):
            file_size = os.path.getsize(downloaded_file)
            if file_size > 50 * 1024 * 1024:
                await message.bot.edit_message_text(
                    "❌ Файл слишком большой (превышает лимит Telegram в 50 МБ).",
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id
                )
                return

            input_file = FSInputFile(downloaded_file)
            
            if downloaded_file.endswith(('.mp3', '.m4a', '.wav', '.opus', '.flac')):
                await message.answer_audio(audio=input_file, caption="🎵 Скачанная музыка через бота")
            else:
                await message.answer_video(video=input_file, caption="📥 Скачанный файл через бота", supports_streaming=True)
            
            await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        else:
            raise Exception("Файл не был найден после скачивания.")

    except Exception as e:
        logging.error(f"Ошибка yt-dlp: {e}")
        try:
            await message.bot.edit_message_text(
                f"❌ <b>Не удалось скачать медиа по ссылке.</b>\nВозможные причины: видео защищено, удалено или файл весит больше 50 МБ.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass


# ==========================================
# ФУНКЦИЯ 2: ШПАРГАЛКИ / БАЗА ЗНАНИЙ
# ==========================================
@router.message(Command("cheats"))
@router.callback_query(F.data == "open_cheats")
async def cmd_cheats(event: Message | CallbackQuery):
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💻 Программирование", callback_data="cheat_cat_code"),
                InlineKeyboardButton(text="🎮 Игровые моды", callback_data="cheat_cat_mods"),
            ],
            [
                InlineKeyboardButton(text="📚 Учеба / Колледж", callback_data="cheat_cat_study"),
            ],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu_fixed")]
        ]
    )
    
    text = "📚 <b>База знаний и шпаргалок</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите интересующую вас категорию:"
    if isinstance(event, CallbackQuery):
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("cheat_cat_"))
async def show_cheat_category(callback: CallbackQuery):
    cat_code = callback.data.split("_")[2]
    
    cursor.execute("SELECT id, title FROM cheat_sheets WHERE category = ?", (cat_code,))
    cheats = cursor.fetchall()

    keyboard = []
    for c_id, title in cheats:
        keyboard.append([InlineKeyboardButton(text=f"📌 {title}", callback_data=f"cheat_view_{c_id}")])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад к категориям", callback_data="open_cheats")])

    await callback.message.edit_text(
        f"📂 <b>Категория: {cat_code.upper()}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите материал для чтения:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cheat_view_"))
async def view_cheat_item(callback: CallbackQuery):
    cheat_id = int(callback.data.split("_")[2])
    
    cursor.execute("SELECT category, title, content FROM cheat_sheets WHERE id = ?", (cheat_id,))
    row = cursor.fetchone()

    if not row:
        await callback.answer("❌ Материал не найден.", show_alert=True)
        return

    category, title, content = row
    text = f"📌 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{content}"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"cheat_cat_{category}")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# КОМАНДЫ НАГРУЗКИ /work
@router.message(Command("work"))
async def cmd_work(message: Message):
    global HEAVY_WORK_MODE
    if message.from_user.id not in ADMIN_IDS:
        return
    HEAVY_WORK_MODE = True
    await message.answer("⚠️ Режим технической сложности **включен**.")


@router.message(Command("rework"))
async def cmd_rework(message: Message):
    global HEAVY_WORK_MODE
    if message.from_user.id not in ADMIN_IDS:
        return
    HEAVY_WORK_MODE = False
    await message.answer("✅ Режим технической сложности **выключен**.")


# /start КОМАНДА
@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"
    args = command.args

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, repeat_mode, language) VALUES (?, ?, 1, 'ru')",
        (user_id, username),
    )
    conn.commit()

    lang = get_user_lang(user_id)
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    is_admin = user_id in ADMIN_IDS

    if args and args.startswith("video_"):
        try:
            video_id = int(args.split("_")[1])
            cursor.execute("SELECT file_id, caption, category FROM videos WHERE id = ?", (video_id,))
            video_data = cursor.fetchone()

            if video_data:
                file_id, caption, category = video_data
                chat_id = message.chat.id

                sent_video = await message.answer_document(
                    document=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🎬 Еще видео", callback_data=f"next_v_{category}")],
                            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu_fixed")]
                        ]
                    )
                )

                async def delete_video():
                    await asyncio.sleep(10)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
                    except Exception:
                        pass
                asyncio.create_task(delete_video())

                warn_msg = await message.answer(text=t["video_deleted_warn"], parse_mode="HTML")

                async def delete_warning():
                    await asyncio.sleep(25)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
                    except Exception:
                        pass
                asyncio.create_task(delete_warning())
                return
        except Exception:
            pass

    await message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "main_menu_fixed")
async def main_menu_fixed(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    await callback.message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )


# ЛОГИКА СОЗДАНИЯ ЗАМЕТОК С ВЫБОРОМ ДАТЫ И ВРЕМЕНИ (FSM)
@router.message(Command("note"))
@router.callback_query(F.data == "start_note")
async def cmd_note_start(event: Message | CallbackQuery, state: FSMContext):
    message = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()
    
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="main_menu_fixed")]]
    )
    await message.answer(
        "📝 <b>Шаг 1/3: Создание заметки</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Введите текст вашей заметки:", 
        reply_markup=cancel_kb, 
        parse_mode="HTML"
    )
    await state.set_state(NoteStates.waiting_for_text)


@router.message(NoteStates.waiting_for_text, F.text)
async def process_note_text(message: Message, state: FSMContext):
    await state.update_data(note_text=message.text)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="main_menu_fixed")]]
    )
    await message.answer(
        "📅 <b>Шаг 2/3: Время отправки</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Укажите дату и время, когда бот должен прислать вам эту заметку.\n"
        "<i>Формат: ДД.ММ.ГГГГ ЧЧ:ММ</i>\n"
        "▫️ Пример: <code>15.09.2026 14:30</code>",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await state.set_state(NoteStates.waiting_for_datetime)


@router.message(NoteStates.waiting_for_datetime, F.text)
async def process_note_datetime(message: Message, state: FSMContext):
    dt_text = message.text.strip()
    # Простейшая валидация введенного формата даты
    try:
        clean_dt = dt_text.replace(" в ", " ").strip()
        datetime.strptime(clean_dt, "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer(
            "⚠️ <b>Неверный формат даты и времени!</b>\n"
            "Пожалуйста, используйте строго формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
            "▫️ Пример: <code>15.09.2026 14:30</code>",
            parse_mode="HTML"
        )
        return

    await state.update_data(note_datetime=dt_text)
    skip_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить медиа", callback_data="skip_media")],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="main_menu_fixed")]
        ]
    )
    await message.answer(
        "📎 <b>Шаг 3/3: Вложение</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Прикрепите фото, видео или документ к заметке (или нажмите «Пропустить медиа»):",
        reply_markup=skip_kb,
        parse_mode="HTML"
    )
    await state.set_state(NoteStates.waiting_for_media)


@router.message(NoteStates.waiting_for_media, F.photo | F.video | F.document)
async def process_note_media_file(message: Message, state: FSMContext):
    media_file_id = None
    media_type = None

    if message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        media_file_id = message.video.file_id
        media_type = "video"
    elif message.document:
        media_file_id = message.document.file_id
        media_type = "document"

    await save_note_to_db(message, state, media_file_id, media_type)


@router.callback_query(NoteStates.waiting_for_media, F.data == "skip_media")
async def skip_note_media(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await save_note_to_db(callback.message, state, None, None, is_callback=True)


async def save_note_to_db(message: Message, state: FSMContext, media_file_id: str, media_type: str, is_callback: bool = False):
    data = await state.get_data()
    user_id = message.chat.id if is_callback else message.from_user.id
    note_text = data.get("note_text")
    note_datetime = data.get("note_datetime")

    cursor.execute(
        "INSERT INTO notes (user_id, note_text, note_datetime, media_file_id, media_type, is_sent) VALUES (?, ?, ?, ?, ?, 0)",
        (user_id, note_text, note_datetime, media_file_id, media_type)
    )
    conn.commit()
    await state.clear()

    success_text = (
        f"✅ <b>Заметка успешно запланирована!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <b>Время отправки:</b> <code>{note_datetime}</code>\n"
        f"📌 <b>Текст:</b> {note_text}"
    )

    is_admin = user_id in ADMIN_IDS
    lang = get_user_lang(user_id)
    keyboard = get_user_keyboard(is_admin, lang)

    if media_file_id:
        if media_type == "photo":
            await message.bot.send_photo(chat_id=user_id, photo=media_file_id, caption=success_text, reply_markup=keyboard, parse_mode="HTML")
        elif media_type == "video":
            await message.bot.send_video(chat_id=user_id, video=media_file_id, caption=success_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.bot.send_document(chat_id=user_id, document=media_file_id, caption=success_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        if is_callback:
            await message.edit_text(success_text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await message.answer(success_text, reply_markup=keyboard, parse_mode="HTML")


# ЛОГИКА ОТПРАВКИ ВИДЕО ПО КАТЕГОРИЯМ
@router.callback_query(F.data.in_({"watch_kids", "watch_porno", "random_video"}) | F.data.startswith("next_v_"))
async def send_video_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    t = LANG_TEXTS[lang]

    category = None
    if callback.data == "watch_kids":
        category = "kids"
    elif callback.data == "watch_porno":
        category = "porno"
    elif callback.data.startswith("next_v_"):
        category = callback.data.split("_")[2]

    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1

    if category:
        if repeat_mode == 1:
            cursor.execute("SELECT id, file_id, caption, category FROM videos WHERE category = ?", (category,))
        else:
            cursor.execute(
                """
                SELECT id, file_id, caption, category FROM videos 
                WHERE category = ? AND id NOT IN (SELECT video_id FROM user_history WHERE user_id = ?)
            """,
                (category, user_id),
            )
    else:
        if repeat_mode == 1:
            cursor.execute("SELECT id, file_id, caption, category FROM videos")
        else:
            cursor.execute(
                """
                SELECT id, file_id, caption, category FROM videos 
                WHERE id NOT IN (SELECT video_id FROM user_history WHERE user_id = ?)
            """,
                (user_id,),
            )

    videos = cursor.fetchall()

    if not videos and repeat_mode == 0:
        cursor.execute("DELETE FROM user_history WHERE user_id = ?", (user_id,))
        conn.commit()
        if category:
            cursor.execute("SELECT id, file_id, caption, category FROM videos WHERE category = ?", (category,))
        else:
            cursor.execute("SELECT id, file_id, caption, category FROM videos")
        videos = cursor.fetchall()

    if not videos:
        await callback.answer(t["no_videos"], show_alert=True)
        return

    video_id, file_id, caption, v_category = random.choice(videos)

    cursor.execute(
        "INSERT OR IGNORE INTO user_history (user_id, video_id) VALUES (?, ?)",
        (user_id, video_id),
    )
    conn.commit()

    chat_id = callback.message.chat.id

    sent_video = await callback.message.answer_document(
        document=file_id,
        caption=caption,
        parse_mode="HTML",
        supports_streaming=True,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Еще видео", callback_data=f"next_v_{v_category}")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu_fixed")]
            ]
        )
    )
    await callback.answer()

    async def delete_video():
        await asyncio.sleep(10)
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
        except Exception:
            pass
    asyncio.create_task(delete_video())

    warn_msg = await callback.message.answer(text=t["video_deleted_warn"], parse_mode="HTML")

    async def delete_warning():
        await asyncio.sleep(25)
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
        except Exception:
            pass
    asyncio.create_task(delete_warning())


# ОСТАЛЬНЫЕ ХЕНДЛЕРЫ
@router.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery):
    lang = callback.data.split("_")[2]
    user_id = callback.from_user.id

    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()

    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    is_admin = user_id in ADMIN_IDS

    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer(t["lang_changed"])


@router.callback_query(F.data == "change_language")
async def change_language_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(Command("language"))
async def cmd_language(message: Message):
    await message.answer(
        "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = get_user_lang(message.from_user.id)
    await message.answer(LANG_TEXTS[lang]["help_text"], parse_mode="HTML")


@router.callback_query(F.data == "help_menu")
async def callback_help(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.answer(LANG_TEXTS[lang]["help_text"], parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "contact_admin")
async def callback_contact_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "💬 <b>Обратная связь</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Опишите вашу проблему или предложение в следующем сообщении:",
        parse_mode="HTML"
    )
    await state.set_state(UserStates.waiting_for_report)
    await callback.answer()


@router.message(Command("random"))
async def cmd_random_text(message: Message):
    fake_callback = CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="0",
        message=message,
        data="random_video"
    )
    await send_video_handler(fake_callback)


@router.message(Command("setting"))
async def cmd_setting(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1
    status_text = "Включено 🟢" if repeat_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat")]
        ]
    )
    await message.answer("⚙️ <b>Панель настроек</b>", reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "toggle_repeat")
async def toggle_repeat_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    current_mode = cursor.fetchone()[0]
    new_mode = 0 if current_mode == 1 else 1

    cursor.execute("UPDATE users SET repeat_mode = ? WHERE user_id = ?", (new_mode, user_id))
    conn.commit()

    status_text = "Включено 🟢" if new_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat")]
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("⚙️ Настройки обновлены!")


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("💬 Опишите проблему в следующем сообщении:", parse_mode="HTML")
    await state.set_state(UserStates.waiting_for_report)


@router.message(UserStates.waiting_for_report)
async def process_report(message: Message, state: FSMContext, bot: Bot):
    report_text = message.text
    user = message.from_user
    user_info = f"@{user.username} (ID: {user.id})" if user.username else f"ID: {user.id}"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🚨 <b>Обращение от {user_info}:</b>\n{report_text}", parse_mode="HTML")
        except Exception:
            pass
    await message.answer("✅ Ваше сообщение отправлено администрации!")
    await state.clear()


@router.message(F.reply_to_message)
async def admin_reply_to_user(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return
    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.text:
        return
    match = re.search(r"ID:\s*(\d+)", reply_msg.text)
    if not match:
        return
    target_user_id = int(match.group(1))
    try:
        await bot.send_message(target_user_id, f"💬 <b>Ответ администрации:</b>\n{message.text}", parse_mode="HTML")
        await message.react([{"type": "emoji", "emoji": "👍"}])
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")


# АДМИН-ПАНЕЛЬ И УПРАВЛЕНИЕ ВИДЕО
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.edit_text("🛠 <b>Панель администратора</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM videos")
    total_videos = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM notes")
    total_notes = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cheat_sheets")
    total_cheats = cursor.fetchone()[0]
    
    await callback.message.edit_text(
        f"📊 <b>Статистика бота:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: <code>{total_users}</code>\n"
        f"🎬 Видеоматериалов: <code>{total_videos}</code>\n"
        f"📝 Заметок в базе: <code>{total_notes}</code>\n"
        f"📚 Шпаргалок: <code>{total_cheats}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel")]]),
        parse_mode="HTML"
    )


# ==========================================
# FastAPI и Запуск приложения через Webhook
# ==========================================
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    # Установка команд бота в интерфейсе Telegram
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="note", description="📝 Создать заметку"),
        BotCommand(command="cheats", description="📚 База знаний"),
        BotCommand(command="random", description="⚡️ Случайное видео"),
        BotCommand(command="setting", description="⚙️ Настройки"),
        BotCommand(command="language", description="🌍 Сменить язык"),
        BotCommand(command="help", description="🆘 Помощь"),
    ])

    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    except Exception as e:
        logging.error(f"Ошибка установки вебхука: {e}")

    # Запускаем фоновый планировщик проверки заметок в отдельной задаче asyncio
    asyncio.create_task(notes_scheduler(bot))


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    from aiogram.types import Update
    update_data = await request.json()
    update = Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/")
async def index():
    return {"status": "Bot is running successfully!"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
