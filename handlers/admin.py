import sqlite3
import os
import logging
import pandas as pd
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, or_f
from config.settings import DB_PATH, ADMIN_ID, BOT_TOKEN, TIMEZONE, COINS_PER_DIFFICULTY, COIN_PENALTY, SUBMISSIONS_DIR
from states.states import AdminStates, UserStates
from callbacks.callbacks import ProblemCB, SubmissionCB, TaskCB
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from zoneinfo import ZoneInfo
import mimetypes

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        "stats": "📊 Umumiy statistika:\n\n",
        "user_stats": "👤 Foydalanuvchi statistikasi:\n\n",
        "select_user": "👤 Foydalanuvchi tanlang:\n\n",
        "no_users": "📪 Foydalanuvchilar topilmadi.",
        "feedback_prompt": "Iltimos, rad etish sababini kiriting:",
        "approved": "✅ Yechim tasdiqlandi! +{coins} tanga qo‘shildi.\n💰 Joriy balans: {total_coins}",
        "rejected": "❌ Yechim rad etildi.\nSabab: {feedback}\n💰 Joriy balans: {coins}",
        "invalid_input": "⚠️ Iltimos, to‘g‘ri ma’lumot yuboring!",
        "excel_generated": "✅ Excel fayl tayyorlandi va yuborildi.",
        "excel_error": "⚠️ Excel faylni yaratishda xatolik yuz berdi."
    }

@admin_router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Faqat adminlar uchun!", protect_content=True)
        logger.warning(f"Non-admin user {message.from_user.id} attempted to access admin panel")
        return
    translations = get_translations()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Yangi masala (ertaga)", callback_data="new_problem_scheduled")],
        [InlineKeyboardButton(text="➕ Yangi masala (hozir)", callback_data="new_problem_immediate")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="stats")],
        [InlineKeyboardButton(text="👤 Foydalanuvchi statistikasi", callback_data="user_stats")]
    ])
    await message.answer(translations["admin_panel"], reply_markup=keyboard, protect_content=True)
    logger.info(f"Admin {message.from_user.id} accessed admin panel")

@admin_router.callback_query(F.data == "new_problem_scheduled")
async def new_problem_scheduled(callback: CallbackQuery, state: FSMContext):
    await state.update_data(send_immediate=False)
    translations = get_translations()
    await callback.message.edit_text(translations["new_problem"], protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_text)
    logger.info(f"Admin {callback.from_user.id} started creating scheduled problem")

@admin_router.callback_query(F.data == "new_problem_immediate")
async def new_problem_immediate(callback: CallbackQuery, state: FSMContext):
    await state.update_data(send_immediate=True)
    translations = get_translations()
    await callback.message.edit_text(translations["new_problem"], protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_text)
    logger.info(f"Admin {callback.from_user.id} started creating immediate problem")

@admin_router.message(AdminStates.waiting_for_problem_text)
async def receive_problem_text(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 5:
        translations = get_translations()
        await message.answer(translations["invalid_input"], protect_content=True)
        logger.warning(f"Admin {message.from_user.id} entered invalid problem text")
        return
    await state.update_data(problem_text=message.text.strip())
    translations = get_translations()
    await message.answer(translations["problem_image"], reply_markup=ReplyKeyboardRemove(), protect_content=True)
    await state.set_state(AdminStates.waiting_for_problem_image)
    logger.info(f"Admin {message.from_user.id} submitted problem text")

@admin_router.message(or_f(AdminStates.waiting_for_problem_image, F.photo, F.document, F.text == "/skip"))
async def receive_problem_image(message: Message, state: FSMContext):
    translations = get_translations()
    image_path = None

    if message.text and message.text.strip() == "/skip":
        await state.update_data(image_path=None)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Oson", callback_data="difficulty_easy"),
             InlineKeyboardButton(text="O‘rta", callback_data="difficulty_medium"),
             InlineKeyboardButton(text="Qiyin", callback_data="difficulty_hard")]
        ])
        await message.answer(translations["select_difficulty"], reply_markup=keyboard, protect_content=True)
        await state.set_state(AdminStates.waiting_for_difficulty)
        logger.info(f"Admin {message.from_user.id} skipped problem image")
        return

    file_obj = None
    filename_ext = ".jpg"
    try:
        if message.photo:
            photo = message.photo[-1]
            file_obj = photo
            filename_ext = ".jpg"
        elif message.document and message.document.mime_type and message.document.mime_type.startswith("image"):
            doc = message.document
            file_obj = doc
            if doc.file_name and os.path.splitext(doc.file_name)[1]:
                filename_ext = os.path.splitext(doc.file_name)[1]
            else:
                guessed = mimetypes.guess_extension(doc.mime_type)
                if guessed:
                    filename_ext = guessed
        else:
            await message.answer(translations["invalid_input"], protect_content=True)
            logger.warning(f"Admin {message.from_user.id} sent unsupported file type or empty message")
            return

        os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = os.path.join(SUBMISSIONS_DIR, f"problem_{timestamp}{filename_ext}")
        await bot.download(file_obj.file_id, destination=image_path)

        try:
            size_bytes = os.path.getsize(image_path)
            max_mb = 8
            if size_bytes > max_mb * 1024 * 1024:
                os.remove(image_path)
                await message.answer(f"⚠️ Rasm juda katta — maksimal {max_mb} MB bo'lishi kerak.", protect_content=True)
                logger.warning(f"Admin {message.from_user.id} uploaded too large image ({size_bytes} bytes)")
                return
        except OSError as e:
            logger.warning(f"Could not determine size for {image_path}: {e}")

        logger.info(f"Admin {message.from_user.id} uploaded problem image: {image_path}")

    except (TelegramBadRequest, TelegramNetworkError) as e:
        logger.error(f"Telegram error while admin {message.from_user.id} uploading image: {e}")
        await message.answer(translations["error"], reply_markup=ReplyKeyboardRemove(), protect_content=True)
        return
    except Exception as e:
        logger.exception(f"Unexpected error saving uploaded image for admin {message.from_user.id}: {e}")
        await message.answer(translations["error"], reply_markup=ReplyKeyboardRemove(), protect_content=True)
        return

    await state.update_data(image_path=image_path)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Oson", callback_data="difficulty_easy"),
         InlineKeyboardButton(text="O‘rta", callback_data="difficulty_medium"),
         InlineKeyboardButton(text="Qiyin", callback_data="difficulty_hard")]
    ])
    await message.answer(translations["select_difficulty"], reply_markup=keyboard, protect_content=True)
    await state.set_state(AdminStates.waiting_for_difficulty)
    logger.info(f"Admin {message.from_user.id} proceeded to select difficulty with image: {image_path}")

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
    logger.info(f"Admin {callback.from_user.id} selected difficulty: {difficulty}")

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
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Database error saving problem for admin {callback.from_user.id}: {e}")
        return
    finally:
        conn.close()

    translations = get_translations()
    if send_immediate:
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
                            f"📘 Masala #{problem_id} ({data['category']} - {data['difficulty']}):\n\n"
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
                            logger.info(f"Sent problem #{problem_id} with image to user {user_id}")
                        else:
                            await bot.send_message(
                                user_id,
                                message_text,
                                reply_markup=submit_keyboard,
                                protect_content=True
                            )
                            logger.info(f"Sent problem #{problem_id} without image to user {user_id}")
                    except (TelegramBadRequest, TelegramNetworkError) as e:
                        logger.error(f"Error sending problem #{problem_id} to user {user_id}: {e}")
            cursor.execute("UPDATE problems SET scheduled_at=NULL WHERE id=?", (problem_id,))
            conn.commit()
        except sqlite3.Error as e:
            await callback.message.edit_text(translations["error"], protect_content=True)
            logger.error(f"Database error sending immediate problem #{problem_id}: {e}")
            return
        finally:
            conn.close()
        await callback.message.edit_text(
            translations["problem_sent"].format(id=problem_id, deadline=deadline),
            protect_content=True
        )
        logger.info(f"Admin {callback.from_user.id} sent immediate problem #{problem_id}")
    else:
        await callback.message.edit_text(
            translations["problem_saved_scheduled"].format(id=problem_id, scheduled_at=scheduled_at),
            protect_content=True
        )
        logger.info(f"Admin {callback.from_user.id} scheduled problem #{problem_id} for {scheduled_at}")
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
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Database error approving submission #{submission_id}: {e}")
        return
    finally:
        conn.close()

    translations = get_translations()
    try:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\nStatus: Ishladi ✅", 
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
        logger.info(f"Admin {callback.from_user.id} approved submission #{submission_id} for user {user_id}")
    except (TelegramBadRequest, TelegramNetworkError) as e:
        logger.error(f"Error notifying user {user_id} for approved submission #{submission_id}: {e}")

@admin_router.callback_query(SubmissionCB.filter(F.action == "reject"))
async def reject_submission(callback: CallbackQuery, callback_data: SubmissionCB, state: FSMContext):
    submission_id = callback_data.submission_id
    await state.update_data(submission_id=submission_id)
    translations = get_translations()
    try:
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
        logger.info(f"Admin {callback.from_user.id} requested feedback for submission #{submission_id}")
    except (TelegramBadRequest, TelegramNetworkError) as e:
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Error requesting feedback for submission #{submission_id}: {e}")

@admin_router.message(AdminStates.waiting_for_feedback)
async def receive_feedback(message: Message, state: FSMContext):
    data = await state.get_data()
    submission_id = data['submission_id']
    feedback = message.text.strip()
    if not feedback or len(feedback) < 5:
        translations = get_translations()
        await message.answer(translations["invalid_input"], protect_content=True)
        logger.warning(f"Admin {message.from_user.id} entered invalid feedback for submission #{submission_id}")
        return

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
    except sqlite3.Error as e:
        translations = get_translations()
        await message.answer(translations["error"], protect_content=True)
        logger.error(f"Database error saving feedback for submission #{submission_id}: {e}")
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
    try:
        await message.bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=message.message_id-1,
            caption=f"Submission #{submission_id}\n\nStatus: Ishlamadi ❌\nFeedback: {feedback}",
            reply_markup=None,
            protect_content=True
        )
        await bot.send_message(
            user_id, 
            translations["rejected"].format(feedback=feedback, coins=coins),
            reply_markup=keyboard,
            protect_content=True
        )
        logger.info(f"Admin {message.from_user.id} rejected submission #{submission_id} with feedback")
    except (TelegramBadRequest, TelegramNetworkError) as e:
        await message.answer(translations["error"], protect_content=True)
        logger.error(f"Error notifying user {user_id} for rejected submission #{submission_id}: {e}")
    await state.clear()

@admin_router.callback_query(SubmissionCB.filter(F.action == "cancel_feedback"))
async def cancel_feedback(callback: CallbackQuery, callback_data: SubmissionCB):
    try:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption.split('\n\n')[0]}\n\nFeedback bekor qilindi",
            reply_markup=None,
            protect_content=True
        )
        logger.info(f"Admin {callback.from_user.id} cancelled feedback for submission #{callback_data.submission_id}")
    except (TelegramBadRequest, TelegramNetworkError) as e:
        translations = get_translations()
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Error cancelling feedback for submission #{callback_data.submission_id}: {e}")

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
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Database error resubmitting submission #{submission_id}: {e}")
        return
    finally:
        conn.close()

    await state.update_data(problem_id=problem_id)
    translations = get_translations()
    try:
        await callback.message.edit_text(
            translations.get("submit_prompt", "📸 Yechim rasmini yuboring:"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
        await state.set_state(UserStates.waiting_for_photo)
        logger.info(f"User {user_id} prompted to resubmit for problem #{problem_id}")
    except (TelegramBadRequest, TelegramNetworkError) as e:
        await callback.message.edit_text(translations["error"], protect_content=True)
        logger.error(f"Error prompting resubmission for user {user_id}, problem #{problem_id}: {e}")

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
        text = translations["stats"]
        text += f"👤 Foydalanuvchilar: {total_users}\n"
        text += f"💰 Umumiy tangalar: {total_coins}\n"
        
        if last_problem:
            problem_id, _, diff, cat, deadline = last_problem
            cursor.execute("""
                SELECT status, COUNT(*) FROM submissions 
                WHERE problem_id=? GROUP BY status
            """, (problem_id,))
            stats = {s: c for s, c in cursor.fetchall()}
            text += f"📘 Masala #{problem_id} ({cat} - {diff}):\n"
            text += f"✅ Tasdiqlangan: {stats.get('approved', 0)}\n"
            text += f"❌ Rad etilgan: {stats.get('rejected', 0)}\n"
            text += f"⏳ Kutmoqda: {stats.get('pending', 0)}\n"
        else:
            text += translations["history_empty"] + "\n"
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 Excel yuklab olish", callback_data="export_stats")],
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, protect_content=True)
        logger.info(f"Admin {callback.from_user.id} viewed general stats")
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(
            translations["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
        logger.error(f"Database error in show_stats for admin {callback.from_user.id}: {e}")
    finally:
        conn.close()

@admin_router.callback_query(F.data == "user_stats")
async def show_user_stats(callback: CallbackQuery, page: int = 0):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name, last_name FROM users ORDER BY user_id LIMIT 5 OFFSET ?", (page * 5,))
        users = cursor.fetchall()
        conn.close()

        translations = get_translations()
        if not users:
            await callback.message.edit_text(
                translations["no_users"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            logger.info(f"Admin {callback.from_user.id} viewed user stats: no users found")
            return

        text = translations["select_user"]
        for user_id, first_name, last_name in users:
            text += f"👤 {first_name} {last_name} (ID: {user_id})\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{first_name} {last_name}",
                callback_data=f"user_detail_{user_id}"
            )] for user_id, first_name, last_name in users
        ])
        if len(users) == 5:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="➡️ Keyingi", callback_data=f"user_stats_page_{page + 1}")
            ])
        if page > 0:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"user_stats_page_{page - 1}")
            ])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())
        ])

        await callback.message.edit_text(text, reply_markup=keyboard, protect_content=True)
        logger.info(f"Admin {callback.from_user.id} viewed user stats page {page}")
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(
            translations["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=TaskCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )
        logger.error(f"Database error in show_user_stats for admin {callback.from_user.id}: {e}")

@admin_router.callback_query(F.data.startswith("user_stats_page_"))
async def show_user_stats_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await show_user_stats(callback, page)

@admin_router.callback_query(F.data.startswith("user_detail_"))
async def show_user_detail(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[-1])
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, last_name, phone_number, coins FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
        if not user:
            translations = get_translations()
            await callback.message.edit_text(
                translations["no_users"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data="user_stats")]
                ]),
                protect_content=True
            )
            logger.warning(f"Admin {callback.from_user.id} tried to view non-existent user {user_id}")
            return

        first_name, last_name, phone_number, coins = user
        cursor.execute("""
            SELECT status, COUNT(*) FROM submissions 
            WHERE user_id=? GROUP BY status
        """, (user_id,))
        stats = {s: c for s, c in cursor.fetchall()}
        cursor.execute("""
            SELECT COUNT(*) FROM problems p 
            LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
            WHERE s.id IS NULL AND p.deadline < ?
        """, (user_id, datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")))
        missed_tasks = cursor.fetchone()[0]
        conn.close()

        translations = get_translations()
        text = translations["user_stats"]
        text += f"👤 Ism: {first_name} {last_name}\n"
        text += f"📞 Telefon: {phone_number}\n"
        text += f"💰 Tangalar: {coins}\n"
        text += f"✅ Tasdiqlangan: {stats.get('approved', 0)}\n"
        text += f"❌ Rad etilgan: {stats.get('rejected', 0)}\n"
        text += f"⏳ Kutmoqda: {stats.get('pending', 0)}\n"
        text += f"⏰ O‘tkazib yuborilgan: {missed_tasks}\n"
        
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="user_stats")]
            ]),
            protect_content=True
        )
        logger.info(f"Admin {callback.from_user.id} viewed stats for user {user_id}")
    except sqlite3.Error as e:
        translations = get_translations()
        await callback.message.edit_text(
            translations["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="user_stats")]
            ]),
            protect_content=True
        )
        logger.error(f"Database error in show_user_detail for admin {callback.from_user.id}, user {user_id}: {e}")

@admin_router.callback_query(F.data == "export_stats")
async def export_stats_to_excel(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, first_name, last_name, phone_number, coins FROM users")
        users = cursor.fetchall()
        
        data = []
        for user_id, first_name, last_name, phone_number, coins in users:
            cursor.execute("""
                SELECT status, COUNT(*) FROM submissions 
                WHERE user_id=? GROUP BY status
            """, (user_id,))
            stats = {s: c for s, c in cursor.fetchall()}
            cursor.execute("""
                SELECT COUNT(*) FROM problems p 
                LEFT JOIN submissions s ON p.id = s.problem_id AND s.user_id=?
                WHERE s.id IS NULL AND p.deadline < ?
            """, (user_id, datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")))
            missed_tasks = cursor.fetchone()[0]
            data.append({
                "User ID": user_id,
                "Ism": first_name,
                "Familya": last_name,
                "Telefon": phone_number,
                "Tangalar": coins,
                "Tasdiqlangan": stats.get("approved", 0),
                "Rad etilgan": stats.get("rejected", 0),
                "Kutmoqda": stats.get("pending", 0),
                "O‘tkazib yuborilgan": missed_tasks
            })
        conn.close()

        if not data:
            translations = get_translations()
            await callback.message.edit_text(
                translations["no_users"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data="stats")]
                ]),
                protect_content=True
            )
            logger.info(f"Admin {callback.from_user.id} attempted to export stats: no users found")
            return

        df = pd.DataFrame(data)
        os.makedirs(SUBMISSIONS_DIR, exist_ok=True)
        excel_path = os.path.join(SUBMISSIONS_DIR, f"stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        df.to_excel(excel_path, index=False)

        translations = get_translations()
        await callback.message.delete()
        await callback.message.answer_document(
            FSInputFile(excel_path),
            caption=translations["excel_generated"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="stats")]
            ]),
            protect_content=True
        )
        logger.info(f"Admin {callback.from_user.id} exported stats to {excel_path}")
    except (sqlite3.Error, pd.errors.EmptyDataError, OSError) as e:
        translations = get_translations()
        await callback.message.edit_text(
            translations["excel_error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="stats")]
            ]),
            protect_content=True
        )
        logger.error(f"Error exporting stats to Excel for admin {callback.from_user.id}: {e}")