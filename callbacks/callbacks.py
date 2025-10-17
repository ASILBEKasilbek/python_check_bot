from aiogram.filters.callback_data import CallbackData

class ProblemCB(CallbackData, prefix="problem"):
    action: str
    problem_id: int

class SubmissionCB(CallbackData, prefix="submission"):
    action: str
    submission_id: int

class LanguageCB(CallbackData, prefix="language"):
    lang: str

class CategoryCB(CallbackData, prefix="category"):
    category: str

class TaskCB(CallbackData, prefix="task"):
    action: str
    problem_id: int