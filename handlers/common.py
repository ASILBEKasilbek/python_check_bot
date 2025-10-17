import sqlite3
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, Contact
from config.settings import DB_PATH, ADMIN_ID, WELCOME_IMAGE, COIN_PENALTY, COINS_PER_DIFFICULTY
from states.states import UserStates
from callbacks.callbacks import TaskCB,ProblemCB
from aiogram.fsm.context import FSMContext
from datetime import datetime
from config.settings import TIMEZONE
import os
from aiogram.types import CallbackQuery
common_router = Router()

def get_translations():
    return {
        "welcome": "🎯 Salom! Har kuni yangi masalalar sizni kutmoqda!\n"
                  "To‘g‘ri yechimlar uchun tanga olasiz, lekin vaqtida topshirmasangiz {penalty} tanga yo‘qotasiz! 💰\n"
                  "Iltimos, ismingizni kiriting:",
        "welcome_no_image": "🎯 Salom! Har kuni yangi masalalar sizni kutmoqda!\n"
                           "To‘g‘ri yechimlar uchun tanga olasiz, lekin vaqtida topshirmasangiz {penalty} tanga yo‘qotasiz! 💰\n"
                           "Iltimos, ismingizni kiriting:",
        "enter_last_name": "Familyangizni kiriting:",
        "enter_phone": "Telefon raqamingizni yuboring (raqam yoki kontakt sifatida):",
        "registration_complete": "✅ Ro‘yxatdan o‘tdingiz! Asosiy menyuni ko‘rish uchun /menu buyrug‘ini ishlating.",
        "already_registered": "⚠️ Siz allaqachon ro‘yxatdan o‘tgansiz. /menu buyrug‘i bilan davom eting.",
        "menu": "📋 Asosiy menyu:",
        "coins": "💰 Sizning tangalaringiz: {coins}",
        "history_empty": "📜 Hozircha masalalar yo‘q.",
        "history": "<b>Oxirgi masalalar:</b>\n\n",
        "leaderboard": "<b>🏆 Eng yaxshi foydalanuvchilar:</b>\n\n",
        "progress": "<b>📈 Sizning yutuqlaringiz:</b>\n\n",
        "error": "⚠️ Xatolik yuz berdi, qayta urinib ko‘ring.",
        "panel": "<b>🎮 Foydalanuvchi paneli:</b>\n\n",
        "today_tasks": "📅 Bugungi masalalar:\n",
        "all_tasks": "<b>📚 Barcha masalalar:</b>\n\n",
        "task_status_pending": "⏳ Kutmoqda",
        "task_status_submitted": "📤 Yuborilgan",
        "task_status_approved": "✅ Tasdiqlangan",
        "task_status_rejected": "❌ Rad etilgan",
        "task_status_missed": "⏰ O‘tkazib yuborilgan"
    }

def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Panel", callback_data=TaskCB(action="panel", problem_id=0).pack()),
         InlineKeyboardButton(text="💰 Tangalar", callback_data=TaskCB(action="coins", problem_id=0).pack())],
        [InlineKeyboardButton(text="📜 Tarix", callback_data=TaskCB(action="history", problem_id=0).pack()),
         InlineKeyboardButton(text="🏆 Reyting", callback_data=TaskCB(action="leaderboard", problem_id=0).pack())],
        [InlineKeyboardButton(text="📈 Yutuqlar", callback_data=TaskCB(action="progress", problem_id=0).pack()),
         InlineKeyboardButton(text="📚 Masalalar", callback_data=TaskCB(action="tasks", problem_id=0).pack())]
    ])

@common_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    translations = get_translations()

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE user_id=?", (user_id,))
        if cursor.fetchone()[0] > 0:
            await message.answer(translations["already_registered"], protect_content=True)
            await state.clear()
            return
    finally:
        conn.close()

    if user_id == ADMIN_ID:
        await message.answer("👑 Admin panelga xush kelibsiz!\n/admin - boshqaruv menyusi", protect_content=True)
    else:
        if os.path.exists(WELCOME_IMAGE):
            await message.answer_photo(
                FSInputFile(WELCOME_IMAGE),
                caption=translations["welcome"].format(penalty=COIN_PENALTY),
                protect_content=True
            )
        else:
            await message.answer(
                translations["welcome_no_image"].format(penalty=COIN_PENALTY),
                protect_content=True
            )
        await state.set_state(UserStates.waiting_for_first_name)

@common_router.message(UserStates.waiting_for_first_name, F.text)
async def receive_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text)
    translations = get_translations()
    await message.answer(translations["enter_last_name"], protect_content=True)
    await state.set_state(UserStates.waiting_for_last_name)

@common_router.message(UserStates.waiting_for_last_name, F.text)
async def receive_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text)
    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Kontakt yuborish", request_contact=True)]
    ])
    await message.answer(translations["enter_phone"], reply_markup=keyboard, protect_content=True)
    await state.set_state(UserStates.waiting_for_phone)

@common_router.message(UserStates.waiting_for_phone, F.contact | F.text.regexp(r"^\+?\d{9,12}$"))
async def receive_phone(message: Message, state: FSMContext):
    phone_number = message.contact.phone_number if message.contact else message.text
    user_id = message.from_user.id
    data = await state.get_data()
    first_name = data["first_name"]
    last_name = data["last_name"]

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (user_id, first_name, last_name, phone_number, coins, language) VALUES (?, ?, ?, ?, 0, 'uz')",
            (user_id, first_name, last_name, phone_number)
        )
        conn.commit()
    except sqlite3.Error:
        await message.answer(get_translations()["error"], protect_content=True)
        return
    finally:
        conn.close()

    translations = get_translations()
    await message.answer(translations["registration_complete"], reply_markup=get_main_menu(), protect_content=True)
    await state.clear()

@common_router.message(Command("menu"))
async def show_menu(message: Message):
    translations = get_translations()
    await message.answer(translations["menu"], reply_markup=get_main_menu(), protect_content=True)

@common_router.callback_query(TaskCB.filter(F.action == "coins"))
async def show_coins(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
        coins = cursor.fetchone()[0]
        translations = get_translations()
        await callback.message.edit_text(
            translations["coins"].format(coins=coins),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    finally:
        conn.close()

@common_router.callback_query(TaskCB.filter(F.action == "history"))
async def show_history(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, difficulty, category, deadline FROM problems ORDER BY created_at DESC LIMIT 5")
        problems = cursor.fetchall()
        translations = get_translations()
        if not problems:
            await callback.message.edit_text(
                translations["history_empty"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        text = translations["history"]
        for pid, ptext, diff, cat, deadline in problems:
            text += f"📘 Masala #{pid} ({cat} - {diff})\n{ptext}\n<i>Deadline: {deadline}</i>\n\n"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    finally:
        conn.close()

@common_router.callback_query(TaskCB.filter(F.action == "leaderboard"))
async def show_leaderboard(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, last_name, coins FROM users ORDER BY coins DESC LIMIT 5")
        leaders = cursor.fetchall()
        translations = get_translations()
        if not leaders:
            await callback.message.edit_text(
                translations["history_empty"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        text = translations["leaderboard"]
        for i, (first_name, last_name, coins) in enumerate(leaders, 1):
            text += f"{i}. {first_name} {last_name} - {coins} 💰\n"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    finally:
        conn.close()

@common_router.callback_query(TaskCB.filter(F.action == "progress"))
async def show_progress(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT status, COUNT(*) FROM submissions 
            WHERE user_id=? GROUP BY status
        """, (callback.from_user.id,))
        stats = {s: c for s, c in cursor.fetchall()}
        cursor.execute("SELECT coins FROM users WHERE user_id=?", (callback.from_user.id,))
        coins = cursor.fetchone()[0]
        
        translations = get_translations()
        text = translations["progress"]
        text += f"✅ Tasdiqlangan: {stats.get('approved', 0)}\n"
        text += f"❌ Rad etilgan: {stats.get('rejected', 0)}\n"
        text += f"⏳ Kutmoqda: {stats.get('pending', 0)}\n"
        text += f"💰 Jami tangalar: {coins}"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    finally:
        conn.close()

@common_router.callback_query(TaskCB.filter(F.action == "panel"))
async def show_panel(callback: CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now(TIMEZONE).date()
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Today's tasks
        cursor.execute("""
            SELECT p.id, p.text, p.difficulty, p.category, p.deadline, s.status
            FROM problems p
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            WHERE date(p.scheduled_at) = ?
        """, (user_id, today.strftime("%Y-%m-%d")))
        today_tasks = cursor.fetchall()
        
        # All tasks
        cursor.execute("""
            SELECT p.id, p.text, p.difficulty, p.category, p.deadline, s.status
            FROM problems p
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            ORDER BY p.created_at DESC LIMIT 5
        """, (user_id,))
        all_tasks = cursor.fetchall()
        
        conn.close()

        translations = get_translations()
        text = translations["panel"]
        
        # Today's tasks
        text += translations["today_tasks"]
        if not today_tasks:
            text += "📪 Bugun uchun masalalar yo‘q.\n\n"
        else:
            for pid, ptext, diff, cat, deadline, status in today_tasks:
                status_text = translations[f"task_status_{status or 'pending'}"]
                text += f"📘 Masala #{pid} ({cat} - {diff}): {status_text}\n"
                text += f"<i>{ptext[:50]}...</i>\n"
                text += f"<i>Deadline: {deadline}</i>\n\n"
        
        # All tasks
        text += translations["all_tasks"]
        for pid, ptext, diff, cat, deadline, status in all_tasks:
            status_text = translations[f"task_status_{status or ('missed' if datetime.strptime(deadline, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE) < datetime.now(TIMEZONE) else 'pending')}"]
            text += f"📘 Masala #{pid} ({cat} - {diff}): {status_text}\n"
            text += f"<i>{ptext[:50]}...</i>\n\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📘 Bugungi masalalar",
                callback_data=TaskCB(action="today_tasks", problem_id=0).pack()
            )],
            [InlineKeyboardButton(
                text="📚 Barcha masalalar",
                callback_data=TaskCB(action="all_tasks", problem_id=0).pack()
            )],
            [InlineKeyboardButton(
                text="🔙 Orqaga",
                callback_data=TaskCB(action="menu", problem_id=0).pack()
            )]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )

@common_router.callback_query(TaskCB.filter(F.action == "today_tasks"))
async def show_today_tasks(callback: CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now(TIMEZONE).date()
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.text, p.difficulty, p.category, p.deadline, s.status
            FROM problems p
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            WHERE date(p.scheduled_at) = ?
        """, (user_id, today.strftime("%Y-%m-%d")))
        tasks = cursor.fetchall()
        conn.close()

        translations = get_translations()
        if not tasks:
            await callback.message.edit_text(
                translations["history_empty"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📘 Masala #{pid} ({cat} - {diff})",
                callback_data=TaskCB(action="view_task", problem_id=pid).pack()
            )] for pid, _, diff, cat, _, _ in tasks
        ] + [[InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]])
        await callback.message.edit_text(translations["today_tasks"], reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
            ]),
            protect_content=True
        )

@common_router.callback_query(TaskCB.filter(F.action == "all_tasks"))
async def show_all_tasks(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id, p.text, p.difficulty, p.category, p.deadline, s.status
            FROM problems p
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            ORDER BY p.created_at DESC LIMIT 5
        """, (user_id,))
        tasks = cursor.fetchall()
        conn.close()

        translations = get_translations()
        if not tasks:
            await callback.message.edit_text(
                translations["history_empty"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📘 Masala #{pid} ({cat} - {diff})",
                callback_data=TaskCB(action="view_task", problem_id=pid).pack()
            )] for pid, _, diff, cat, _, _ in tasks
        ] + [[InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]])
        await callback.message.edit_text(translations["all_tasks"], reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
            ]),
            protect_content=True
        )

@common_router.callback_query(TaskCB.filter(F.action == "view_task"))
async def view_task(callback: CallbackQuery, callback_data: TaskCB):
    user_id = callback.from_user.id
    problem_id = callback_data.problem_id
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.text, p.image_path, p.difficulty, p.category, p.deadline, s.status
            FROM problems p
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            WHERE p.id=?
        """, (user_id, problem_id))
        task = cursor.fetchone()
        conn.close()

        translations = get_translations()
        if not task:
            await callback.message.edit_text(
                translations["error"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        text, image_path, diff, cat, deadline, status = task
        status_text = translations[f"task_status_{status or ('missed' if datetime.strptime(deadline, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TIMEZONE) < datetime.now(TIMEZONE) else 'pending')}"]
        message_text = (
            f"<b>📘 Masala #{problem_id} ({cat} - {diff}):</b>\n\n"
            f"{text}\n\n<i>Deadline: {deadline}</i>\n"
            f"<b>Status: {status_text}</b>"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
        ])
        if not status and datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE) > datetime.now(TIMEZONE):
            keyboard.inline_keyboard.insert(0, [
                InlineKeyboardButton(
                    text="✅ Yechim yuborish",
                    callback_data=ProblemCB(action="submit", problem_id=problem_id).pack()
                )
            ])

        if image_path and os.path.exists(image_path):
            await callback.message.delete()
            await callback.message.answer_photo(
                FSInputFile(image_path),
                caption=message_text,
                reply_markup=keyboard,
                protect_content=True
            )
        else:
            await callback.message.edit_text(message_text, reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="panel", problem_id=0).pack())]
            ]),
            protect_content=True
        )

@common_router.callback_query(TaskCB.filter(F.action == "menu"))
async def show_menu_callback(callback: CallbackQuery):
    translations = get_translations()
    await callback.message.edit_text(translations["menu"], reply_markup=get_main_menu(), protect_content=True)