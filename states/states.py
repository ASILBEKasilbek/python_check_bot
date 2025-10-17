from aiogram.fsm.state import StatesGroup, State

class UserStates(StatesGroup):
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_phone = State()
    waiting_for_photo = State()

class AdminStates(StatesGroup):
    waiting_for_problem_text = State()
    waiting_for_problem_image = State()
    waiting_for_difficulty = State()
    waiting_for_category = State()
    waiting_for_feedback = State()