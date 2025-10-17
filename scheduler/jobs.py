import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from config.settings import DB_PATH, BOT_TOKEN, ADMIN_ID, TIMEZONE, COINS_PER_DIFFICULTY, COIN_PENALTY
from callbacks.callbacks import ProblemCB
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from zoneinfo import ZoneInfo
import os
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        protect_content=True
    )
)

def get_translations():
    return {
        "task_notification": "<b>📘 Kunlik masala #{id} ({category} - {difficulty}):</b>\n\n{text}\n\n"
                           "<i>Deadline: {deadline}</i>\n"
                           "🎁 To‘g‘ri yechim uchun {coins} tanga!",
        "reminder": "⏰ Masala #{id} ({category} - {difficulty}) uchun 1 soat qoldi!\n"
                   "Tezroq yechim yuboring: {text}\n<i>Deadline: {deadline}</i>",
        "penalty": "⚠️ Masala #{id} topshirmadingiz! {penalty} tanga ayirildi.\n💰 Joriy balans: {coins}"
    }

async def check_deadlines():
    now = datetime.now(TIMEZONE)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, deadline FROM problems")
        problems = cursor.fetchall()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        
        translations = get_translations()
        for pid, deadline in problems:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
            if deadline_dt < now:
                cursor.execute("SELECT user_id FROM submissions WHERE problem_id=?", (pid,))
                submitted_users = {row[0] for row in cursor.fetchall()}
                for user_id in users:
                    if user_id != ADMIN_ID and user_id not in submitted_users:
                        cursor.execute("UPDATE users SET coins = GREATEST(coins - ?, 0) WHERE user_id=?", 
                                      (COIN_PENALTY, user_id))
                        cursor.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
                        coins = cursor.fetchone()[0]
                        try:
                            await bot.send_message(
                                user_id,
                                translations["penalty"].format(id=pid, penalty=COIN_PENALTY, coins=coins),
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="menu System: menu", problem_id=0).pack())]
                                ]),
                                protect_content=True
                            )
                        except Exception:
                            pass
                cursor.execute("""
                    UPDATE submissions
                    SET status='auto_rejected', reviewed_at=CURRENT_TIMESTAMP
                    WHERE problem_id=? AND status='pending'
                """, (pid,))
        conn.commit()
    except sqlite3.Error:
        print("Deadline check error")
    finally:
        conn.close()

async def send_daily_problems():
    now = datetime.now(TIMEZONE)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text, image_path, difficulty, category, deadline FROM problems "
            "WHERE scheduled_at <= ? AND scheduled_at IS NOT NULL",
            (now.strftime("%Y-%m-%d %H:%M:%S"),)
        )
        problems = cursor.fetchall()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        
        translations = get_translations()
        for problem_id, text, image_path, difficulty, category, deadline in problems:
            coins = COINS_PER_DIFFICULTY.get(difficulty.lower(), COINS_PER_DIFFICULTY["medium"])
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
                        message_text = translations["task_notification"].format(
                            id=problem_id, text=text, category=category, difficulty=difficulty,
                            deadline=deadline, coins=coins
                        )
                        if image_path and os.path.exists(image_path):
                            await bot.send_photo(
                                user_id,
                                FSInputFile(image_path),
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
        print("Problem sending error")
    finally:
        conn.close()

async def send_deadline_reminders():
    now = datetime.now(TIMEZONE)
    one_hour_later = now + timedelta(hours=1)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, text, difficulty, category, deadline FROM problems "
            "WHERE deadline BETWEEN ? AND ?",
            (now.strftime("%Y-%m-%d %H:%M:%S"), one_hour_later.strftime("%Y-%m-%d %H:%M:%S"))
        )
        problems = cursor.fetchall()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        
        translations = get_translations()
        for problem_id, text, difficulty, category, deadline in problems:
            cursor.execute("SELECT user_id FROM submissions WHERE problem_id=?", (problem_id,))
            submitted_users = {row[0] for row in cursor.fetchall()}
            
            for user_id in users:
                if user_id != ADMIN_ID and user_id not in submitted_users:
                    try:
                        message_text = translations["reminder"].format(
                            id=problem_id, text=text[:100] + "..." if len(text) > 100 else text,
                            category=category, difficulty=difficulty, deadline=deadline
                        )
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="✅ Yechim yuborish",
                                callback_data=ProblemCB(action="submit", problem_id=problem_id).pack()
                            )]
                        ])
                        await bot.send_message(user_id, message_text, reply_markup=keyboard, protect_content=True)
                    except Exception:
                        pass
    except sqlite3.Error:
        print("Reminder sending error")
    finally:
        conn.close()