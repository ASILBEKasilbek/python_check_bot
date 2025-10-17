import sqlite3
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from config.settings import DB_PATH, ADMIN_ID, BOT_TOKEN, TIMEZONE, COINS_PER_DIFFICULTY, COIN_PENALTY
from states.states import AdminStates,UserStates
from callbacks.callbacks import ProblemCB, SubmissionCB,TaskCB
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from zoneinfo import ZoneInfo
import os

admin_router = Router()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        protect_content=True
    )
)

def get_translations():
    return {
        "admin_panel": "👑 Admin panel:",
        "new_problem": "📝 Masala matnini yuboring:",
        "problem_image": "📸 Masala uchun rasm yuboring (agar kerak bo‘lmasa, /skip deb yozing):",
        "select_difficulty": "📊 Masala qiyinligini tanlang:",
        "select_category": "📚 Masala kategoriyasini tanlang:",
        "send_option": "📤 Masalani qachon yuborishni tanlang:",
        "problem_saved_scheduled": "✅ Masala #{id} saqlandi! Foydalanuvchilarga {scheduled_at} da yuboriladi.",
        "problem_sent": "✅ Masala #{id} foydalanuvchilarga yuborildi! Deadline: {deadline}",
        "error": "⚠️ Xatolik yuz berdi, qayta urinib ko‘ring.",
        "stats": "<b>📊 Statistika:</b>\n\n",
        "feedback_prompt": "Iltimos, rad etish sababini kiriting:",
        "approved": "✅ Yechim tasdiqlandi! +{coins} tanga qo‘shildi.\n💰 Joriy balans: {total_coins}",
        "rejected": "❌ Yechim rad etildi.\nSabab: {feedback}\n💰 Joriy balans: {coins}"
    }

@admin_router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Faqat adminlar uchun!", protect_content=True)
        return
    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi masala (ertaga)", callback_data="new_problem_scheduled")],
        [InlineKeyboardButton(text="➕ Yangi masala (hozir)", callback_data="new_problem_immediate")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="stats")]
    ])
    await message.answer(translations["admin_panel"], reply_markup=keyboard, protect_content=True)

@admin_router.callback_query(F.data == "new_problem_scheduled")
async def new_problem_scheduled(callback: CallbackQuery, state: FSMContext):
    await state.update_data(send_immediate=False)
    translations = get_translations()
    await callback.message.edit_text(translations["new_problem"], protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_text)

@admin_router.callback_query(F.data == "new_problem_immediate")
async def new_problem_immediate(callback: CallbackQuery, state: FSMContext):
    await state.update_data(send_immediate=True)
    translations = get_translations()
    await callback.message.edit_text(translations["new_problem"], protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_text)

@admin_router.message(AdminStates.waiting_for_problem_text)
async def receive_problem_text(message: Message, state: FSMContext):
    await state.update_data(problem_text=message.text)
    translations = get_translations()
    await message.answer(translations["problem_image"], protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_image)

@admin_router.message(AdminStates.waiting_for_problem_image, F.photo | F.text == "/skip")
async def receive_problem_image(message: Message, state: FSMContext):
    image_path = None
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        image_path = f"submissions/problem_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        await bot.download_file(file.file_path, image_path)
    
    await state.update_data(image_path=image_path)
    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Oson", callback_data="difficulty_easy"),
         InlineKeyboardButton(text="O‘rta", callback_data="difficulty_medium"),
         InlineKeyboardButton(text="Qiyin", callback_data="difficulty_hard")]
    ])
    await message.answer(translations["select_difficulty"], reply_markup=keyboard, protect_content=True)
    await state.set_state(AdminStates.waiting_for_difficulty)

@admin_router.callback_query(F.data.startswith("difficulty_"))
async def receive_difficulty(callback: CallbackQuery, state: FSMContext):
    difficulty = {"difficulty_easy": "Oson", "difficulty_medium": "O‘rta", "difficulty_hard": "Qiyin"}[callback.data]
    await state.update_data(difficulty=difficulty)
    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Matematika", callback_data="category_math"),
         InlineKeyboardButton(text="Dasturlash", callback_data="category_programming")],
        [InlineKeyboardButton(text="Mantiq", callback_data="category_logic"),
         InlineKeyboardButton(text="Boshqa", callback_data="category_other")]
    ])
    await callback.message.edit_text(translations["select_category"], reply_markup=keyboard, protect_content=True)
    await state.set_state(AdminStates.waiting_for_category)

@admin_router.callback_query(F.data.startswith("category_"))
async def receive_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1].capitalize()
    await state.update_data(category=category)
    
    data = await state.get_data()
    send_immediate = data.get("send_immediate", False)
    now = datetime.now(TIMEZONE)
    if send_immediate:
        deadline = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        scheduled_at = now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        deadline = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        scheduled_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour >= 0:
            scheduled_at += timedelta(days=1)
        scheduled_at = scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO problems (text, image_path, difficulty, category, deadline, scheduled_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (data['problem_text'], data.get('image_path'), data['difficulty'], data['category'], 
             deadline, scheduled_at)
        )
        problem_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error:
        translations = get_translations()
        await callback.message.edit_text(translations["error"], protect_content=True)
        return
    finally:
        conn.close()

    translations = get_translations()
    if send_immediate:
        # Send task immediately
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = [row[0] for row in cursor.fetchall()]
            coins = COINS_PER_DIFFICULTY.get(data['difficulty'].lower(), COINS_PER_DIFFICULTY["medium"])
            submit_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Yechim yuborish",
                        callback_data=ProblemCB(action="submit", problem_id=problem_id).pack()
                    )]
                ]
            )
            for user_id in users:
                if user_id != ADMIN_ID:
                    try:
                        message_text = (
                            f"<b>📘 Masala #{problem_id} ({data['category']} - {data['difficulty']}):</b>\n\n"
                            f"{data['problem_text']}\n\n<i>Deadline: {deadline}</i>\n"
                            f"🎁 To‘g‘ri yechim uchun {coins} tanga!"
                        )
                        if data.get('image_path') and os.path.exists(data['image_path']):
                            await bot.send_photo(
                                user_id,
                                FSInputFile(data['image_path']),
                                caption=message_text,
                                reply_markup=submit_keyboard,
                                protect_content=True
                            )
                        else:
                            await bot.send_message(
                                user_id,
                                message_text,
                                reply_markup=submit_keyboard,
                                protect_content=True
                            )
                    except Exception:
                        pass
            cursor.execute("UPDATE problems SET scheduled_at=NULL WHERE id=?", (problem_id,))
            conn.commit()
        except sqlite3.Error:
            await callback.message.edit_text(translations["error"], protect_content=True)
            return
        finally:
            conn.close()
        await callback.message.edit_text(
            translations["problem_sent"].format(id=problem_id, deadline=deadline),
            protect_content=True
        )
    else:
        await callback.message.edit_text(
            translations["problem_saved_scheduled"].format(id=problem_id, scheduled_at=scheduled_at),
            protect_content=True
        )
    await state.clear()

@admin_router.callback_query(SubmissionCB.filter(F.action == "approve"))
async def approve_submission(callback: CallbackQuery, callback_data: SubmissionCB):
    submission_id = callback_data.submission_id
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, problem_id FROM submissions WHERE id=?", (submission_id,))
        user_id, problem_id = cursor.fetchone()
        cursor.execute("SELECT difficulty FROM problems WHERE id=?", (problem_id,))
        difficulty = cursor.fetchone()[0]
        coins_to_add = COINS_PER_DIFFICULTY.get(difficulty.lower(), COINS_PER_DIFFICULTY["medium"])
        
        cursor.execute("UPDATE submissions SET status='approved', reviewed_at=CURRENT_TIMESTAMP WHERE id=?", 
                      (submission_id,))
        cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", 
                      (coins_to_add, user_id))
        cursor.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
        coins = cursor.fetchone()[0]
        conn.commit()
    except sqlite3.Error:
        await callback.message.edit_text(translations["error"], protect_content=True)
        return
    finally:
        conn.close()

    translations = get_translations()
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n<b>Status: Ishladi ✅</b>", 
        reply_markup=None,
        protect_content=True
    )
    await bot.send_message(
        user_id, 
        translations["approved"].format(coins=coins_to_add, total_coins=coins),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
        ]),
        protect_content=True
    )

@admin_router.callback_query(SubmissionCB.filter(F.action == "reject"))
async def reject_submission(callback: CallbackQuery, callback_data: SubmissionCB, state: FSMContext):
    submission_id = callback_data.submission_id
    await state.update_data(submission_id=submission_id)
    translations = get_translations()
    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n{translations['feedback_prompt']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⏎ Bekor qilish",
                callback_data=SubmissionCB(action="cancel_feedback", submission_id=submission_id).pack()
            )]
        ]),
        protect_content=True
    )
    await state.set_state(AdminStates.waiting_for_feedback)

@admin_router.message(AdminStates.waiting_for_feedback)
async def receive_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    submission_id = data['submission_id']
    feedback = message.text
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE submissions SET status='rejected', reviewed_at=CURRENT_TIMESTAMP, feedback=? WHERE id=?", 
                      (feedback, submission_id))
        cursor.execute("SELECT user_id, coins FROM users WHERE user_id IN "
                     "(SELECT user_id FROM submissions WHERE id=?)", 
                     (submission_id,))
        user_id, coins = cursor.fetchone()
        conn.commit()
    except sqlite3.Error:
        await message.answer(translations["error"], protect_content=True)
        return
    finally:
        conn.close()

    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Qayta yuborish",
            callback_data=SubmissionCB(action="resubmit", submission_id=submission_id).pack()
        )],
        [InlineKeyboardButton(
            text="🔙 Orqaga",
            callback_data=TaskCB(action="menu", problem_id=0).pack()
        )]
    ])
    await message.bot.edit_message_caption(
        chat_id=message.chat.id,
        message_id=message.message_id-1,
        caption=f"Submission #{submission_id}\n\n<b>Status: Ishlamadi ❌</b>\nFeedback: {feedback}",
        reply_markup=None,
        protect_content=True
    )
    await bot.send_message(
        user_id, 
        translations["rejected"].format(feedback=feedback, coins=coins),
        reply_markup=keyboard,
        protect_content=True
    )
    await state.clear()

@admin_router.callback_query(SubmissionCB.filter(F.action == "cancel_feedback"))
async def cancel_feedback(callback: CallbackQuery, callback_data: SubmissionCB):
    await callback.message.edit_caption(
        caption=f"{callback.message.caption.split('\n\n')[0]}\n\n<b>Feedback bekor qilindi</b>",
        reply_markup=None,
        protect_content=True
    )

@admin_router.callback_query(SubmissionCB.filter(F.action == "resubmit"))
async def resubmit_submission(callback: CallbackQuery, callback_data: SubmissionCB, state: FSMContext):
    submission_id = callback_data.submission_id
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, problem_id FROM submissions WHERE id=?", (submission_id,))
        user_id, problem_id = cursor.fetchone()
        cursor.execute("DELETE FROM submissions WHERE id=?", (submission_id,))
        conn.commit()
    except sqlite3.Error:
        await callback.message.edit_text(translations["error"], protect_content=True)
        return
    finally:
        conn.close()

    await state.update_data(problem_id=problem_id)
    translations = get_translations()
    await callback.message.edit_text(
        translations["submit_prompt"],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
        ]),
        protect_content=True
    )
    await state.set_state(UserStates.waiting_for_photo)

@admin_router.callback_query(F.data == "stats")
async def show_stats(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(coins) FROM users")
        total_coins = cursor.fetchone()[0] or 0
        cursor.execute("SELECT id, text, difficulty, category, deadline FROM problems ORDER BY id DESC LIMIT 1")
        last_problem = cursor.fetchone()
        
        translations = get_translations()
        if not last_problem:
            await callback.message.edit_text(
                translations["history_empty"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        problem_id, _, diff, cat, deadline = last_problem
        cursor.execute("""
            SELECT status, COUNT(*) FROM submissions 
            WHERE problem_id=? GROUP BY status
        """, (problem_id,))
        stats = {s: c for s, c in cursor.fetchall()}
        conn.close()

        text = translations["stats"]
        text += f"👤 Foydalanuvchilar: {total_users}\n"
        text += f"💰 Umumiy tangalar: {total_coins}\n"
        text += f"📘 Masala #{problem_id} ({cat} - {diff}):\n"
        text += f"✅ Tasdiqlangan: {stats.get('approved', 0)}\n"
        text += f"❌ Rad etilgan: {stats.get('rejected', 0)}\n"
        text += f"⏳ Kutmoqda: {stats.get('pending', 0)}\n"
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
    except sqlite3.Error:
        await callback.message.edit_text(
            translations["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )