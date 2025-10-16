import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
    FSInputFile,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

# ---------------------------------------
# Konfiguratsiya
# ---------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
# ADMIN_ID = 5306481482  # o'zingizning ID'ingiz
ADMIN_ID=6182449219
SUBMISSIONS_DIR = Path("submissions")
SUBMISSIONS_DIR.mkdir(exist_ok=True)
DB_PATH = "bot.db"


# ---------------------------------------
# Ma'lumotlar bazasi
# ---------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            deadline TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            problem_id INTEGER,
            photo_path TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            reviewed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (problem_id) REFERENCES problems (id)
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------
# Holatlar
# ---------------------------------------
class AdminStates(StatesGroup):
    waiting_for_problem = State()
    waiting_for_deadline = State()


class UserStates(StatesGroup):
    waiting_for_photo = State()


# ---------------------------------------
# CallbackData yangi formatda
# ---------------------------------------
class ProblemCB(CallbackData, prefix="problem"):
    action: str
    problem_id: int


class SubmissionCB(CallbackData, prefix="submission"):
    action: str
    submission_id: int


# ---------------------------------------
# Router va Dispatcher
# ---------------------------------------
dp = Dispatcher(storage=MemoryStorage())
admin_router = Router()
user_router = Router()
dp.include_router(admin_router)
dp.include_router(user_router)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        protect_content=False
    )
)


# ---------------------------------------
# /start
# ---------------------------------------
@admin_router.message(CommandStart())
@user_router.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

    if user_id == ADMIN_ID:
        await message.answer("👑 Admin panelga xush kelibsiz!\n/admin - boshqaruv menyusi")
    else:
        await message.answer(f"Salom, {username}! Har kuni masalalar sizga yuboriladi.")


# ---------------------------------------
# Admin panel
# ---------------------------------------
@admin_router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi masala yuborish", callback_data="new_problem")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="stats")]
    ])
    await message.answer("Admin panel:", reply_markup=keyboard)


# ---------------------------------------
# Yangi masala
# ---------------------------------------
@admin_router.callback_query(F.data == "new_problem")
async def new_problem_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Masala matnini yuboring:")
    await state.set_state(AdminStates.waiting_for_problem)


@admin_router.message(AdminStates.waiting_for_problem)
async def receive_problem_text(message: Message, state: FSMContext):
    await state.update_data(problem_text=message.text)
    await message.answer("Deadline'ni kiriting (YYYY-MM-DD HH:MM:SS formatida):")
    await state.set_state(AdminStates.waiting_for_deadline)


@admin_router.message(AdminStates.waiting_for_deadline)
async def receive_deadline(message: Message, state: FSMContext):
    data = await state.get_data()
    deadline = message.text
    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        await message.answer("❌ Noto‘g‘ri format! Qaytadan kiriting.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO problems (text, deadline) VALUES (?, ?)", (data['problem_text'], deadline))
    problem_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Barcha userlarga yuborish
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    current_problem_text = (
        f"<b>Kunlik masala #{problem_id}:</b>\n\n{data['problem_text']}\n\n"
        f"<i>Deadline: {deadline}</i>"
    )
    submit_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Yechim yuborish",
                callback_data=ProblemCB(action="submit", problem_id=problem_id).pack()
            )]
        ]
    )

    for (user_id,) in users:
        if user_id != ADMIN_ID:
            try:
                await bot.send_message(user_id, current_problem_text, reply_markup=submit_keyboard)
            except Exception:
                pass

    await state.clear()
    await message.answer(f"Masala #{problem_id} yuborildi! {len(users)-1} ta foydalanuvchiga.")


# ---------------------------------------
# User submit
# ---------------------------------------
@user_router.callback_query(ProblemCB.filter(F.action == "submit"))
async def user_submit_start(callback: CallbackQuery, callback_data: ProblemCB, state: FSMContext):
    await state.update_data(problem_id=callback_data.problem_id)
    await callback.message.edit_text("📸 Yechimingiz rasmini yuboring:")
    await state.set_state(UserStates.waiting_for_photo)


@user_router.message(UserStates.waiting_for_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    problem_id = data['problem_id']
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)

    file_path = SUBMISSIONS_DIR / f"{message.from_user.id}_{problem_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    await bot.download_file(file.file_path, file_path)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO submissions (user_id, problem_id, photo_path) VALUES (?, ?, ?)",
        (message.from_user.id, problem_id, str(file_path))
    )
    submission_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer("✅ Rasm qabul qilindi! Admin tekshiradi.")

    # Admin'ga yuborish
    photo_to_send = FSInputFile(file_path)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Ishladi",
                callback_data=SubmissionCB(action="approve", submission_id=submission_id).pack()
            ),
            InlineKeyboardButton(
                text="❌ Ishlamadi",
                callback_data=SubmissionCB(action="reject", submission_id=submission_id).pack()
            )
        ]
    ])
    await bot.send_photo(
        ADMIN_ID,
        photo_to_send,
        caption=f"Submission #{submission_id}\nUser: {message.from_user.id}\nProblem #{problem_id}",
        reply_markup=keyboard
    )


# ---------------------------------------
# Admin review
# ---------------------------------------
@admin_router.callback_query(SubmissionCB.filter(F.action == "approve"))
async def approve_submission(callback: CallbackQuery, callback_data: SubmissionCB):
    submission_id = callback_data.submission_id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE submissions SET status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (submission_id,))
    cursor.execute("SELECT user_id FROM submissions WHERE id=?", (submission_id,))
    user_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    await callback.message.edit_caption(callback.message.caption + "\n\n<b>Status: Ishladi ✅</b>", reply_markup=None)
    await bot.send_message(user_id, "🎉 Sizning yechimingiz tasdiqlandi! ✅")


@admin_router.callback_query(SubmissionCB.filter(F.action == "reject"))
async def reject_submission(callback: CallbackQuery, callback_data: SubmissionCB):
    submission_id = callback_data.submission_id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE submissions SET status='rejected', reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (submission_id,))
    cursor.execute("SELECT user_id FROM submissions WHERE id=?", (submission_id,))
    user_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()

    await callback.message.edit_caption(callback.message.caption + "\n\n<b>Status: Ishlamadi ❌</b>", reply_markup=None)
    await bot.send_message(user_id, "❌ Sizning yechimingiz rad etildi.")


# ---------------------------------------
# Statistika
# ---------------------------------------
@admin_router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT id, text, deadline FROM problems ORDER BY id DESC LIMIT 1")
    last_problem = cursor.fetchone()
    if not last_problem:
        await callback.message.edit_text("Hozircha masalalar yo‘q.")
        return

    problem_id, _, deadline = last_problem
    cursor.execute("""
        SELECT status, COUNT(*) FROM submissions WHERE problem_id=? GROUP BY status
    """, (problem_id,))
    stats = {s: c for s, c in cursor.fetchall()}
    conn.close()

    text = f"""
<b>Statistika:</b>
👤 Umumiy foydalanuvchilar: {total_users}
📘 Masala #{problem_id}:
✅ Ishladi: {stats.get('approved', 0)}
❌ Ishlamadi: {stats.get('rejected', 0)}
⏳ Kutmoqda: {stats.get('pending', 0)}
"""
    await callback.message.edit_text(text)


# ---------------------------------------
# Avtomatik deadline tekshirish
# ---------------------------------------
async def check_deadlines():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, deadline FROM problems")
    problems = cursor.fetchall()
    for pid, deadline in problems:
        if datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S") < datetime.now():
            cursor.execute("""
                UPDATE submissions
                SET status='auto_rejected', reviewed_at=CURRENT_TIMESTAMP
                WHERE problem_id=? AND status='pending'
            """, (pid,))
    conn.commit()
    conn.close()


# ---------------------------------------
# Main
# ---------------------------------------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_deadlines, "interval", minutes=30)
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
