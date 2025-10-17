import sqlite3
from datetime import datetime
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from config.settings import DB_PATH, SUBMISSIONS_DIR, BOT_TOKEN, ADMIN_ID
from states.states import UserStates
from callbacks.callbacks import ProblemCB, SubmissionCB, CategoryCB
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

user_router = Router()
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML,
        protect_content=True
    )
)

def get_translations():
    return {
        "submit_prompt": "📸 Yechimingiz rasmini yuboring:",
        "already_submitted": "⚠️ Siz bu masalaga allaqachon yechim yuborgansiz!",
        "submission_accepted": "✅ Yechimingiz qabul qilindi! Admin tekshiradi.",
        "submission_error": "⚠️ Yechimni saqlashda xatolik yuz berdi.",
        "approved": "🎉 Yechimingiz tasdiqlandi! +{coins} tanga qo‘shildi.\n💰 Joriy balans: {total_coins}",
        "rejected": "❌ Yechimingiz rad etildi.\nSabab: {feedback}\n💰 Joriy balans: {coins}",
        "tasks": "📚 Masala kategoriyasini tanlang:",
        "no_tasks": "📜 Ushbu kategoriyada masalalar yo‘q."
    }

@user_router.callback_query(ProblemCB.filter(F.action == "submit"))
async def user_submit_start(callback: CallbackQuery, callback_data: ProblemCB, state: FSMContext):
    user_id = callback.from_user.id
    problem_id = callback_data.problem_id
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE user_id=? AND problem_id=?", 
                      (user_id, problem_id))
        translations = get_translations()
        if cursor.fetchone()[0] > 0:
            await callback.message.edit_text(
                translations["already_submitted"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="panel", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return
    finally:
        conn.close()

    await state.update_data(problem_id=problem_id)
    await callback.message.edit_text(
        translations["submit_prompt"],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="panel", problem_id=0).pack())]
        ]),
        protect_content=True
    )
    await state.set_state(UserStates.waiting_for_photo)

@user_router.message(UserStates.waiting_for_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    problem_id = data['problem_id']
    user_id = message.from_user.id
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM submissions WHERE user_id=? AND problem_id=?", 
                      (user_id, problem_id))
        translations = get_translations()
        if cursor.fetchone()[0] > 0:
            await message.answer(
                translations["already_submitted"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="panel", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            await state.clear()
            return
    finally:
        conn.close()

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_path = SUBMISSIONS_DIR / f"{user_id}_{problem_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    await bot.download_file(file.file_path, file_path)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO submissions (user_id, problem_id, photo_path) VALUES (?, ?, ?)",
            (user_id, problem_id, str(file_path))
        )
        submission_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error:
        await message.answer(
            translations["submission_error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="panel", problem_id=0).pack())]
            ]),
            protect_content=True
        )
        return
    finally:
        conn.close()

    await state.clear()
    await message.answer(
        translations["submission_accepted"],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="panel", problem_id=0).pack())]
        ]),
        protect_content=True
    )

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
        caption=f"Submission #{submission_id}\nUser: {user_id}\nProblem #{problem_id}",
        reply_markup=keyboard,
        protect_content=True
    )

@user_router.callback_query(ProblemCB.filter(F.action == "tasks"))
async def show_tasks(callback: CallbackQuery):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM problems")
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()

        translations = get_translations()
        if not categories:
            await callback.message.edit_text(
                translations["no_tasks"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="menu", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=cat, callback_data=CategoryCB(category=cat).pack())]
            for cat in categories
        ] + [[InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="menu", problem_id=0).pack())]])
        await callback.message.edit_text(translations["tasks"], reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="menu", problem_id=0).pack())]
            ]),
            protect_content=True
        )

@user_router.callback_query(CategoryCB.filter())
async def show_category_tasks(callback: CallbackQuery, callback_data: CategoryCB):
    category = callback_data.category
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, text, difficulty, deadline FROM problems WHERE category=? ORDER BY created_at DESC LIMIT 5",
                      (category,))
        problems = cursor.fetchall()
        conn.close()

        translations = get_translations()
        if not problems:
            await callback.message.edit_text(
                translations["no_tasks"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="tasks", problem_id=0).pack())]
                ]),
                protect_content=True
            )
            return

        text = translations["history"]
        for pid, ptext, diff, deadline in problems:
            text += f"📘 Masala #{pid} ({category} - {diff})\n{ptext}\n<i>Deadline: {deadline}</i>\n\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="tasks", problem_id=0).pack())]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard, protect_content=True)
    except sqlite3.Error:
        await callback.message.edit_text(
            get_translations()["error"],
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data=ProblemCB(action="tasks", problem_id=0).pack())]
            ]),
            protect_content=True
        )