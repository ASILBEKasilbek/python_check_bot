import os
from pathlib import Path
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Load environment variables
load_dotenv()

# Basic configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
# ADMIN_ID = 6182449219
ADMIN_ID = 5306481482  # o'zingizning ID'ingiz
SUBMISSIONS_DIR = Path("submissions")
SUBMISSIONS_DIR.mkdir(exist_ok=True)
DB_PATH = "bot5.db"
TIMEZONE = ZoneInfo("Asia/Tashkent")
COINS_PER_DIFFICULTY = {
    "easy": 5,
    "medium": 10,
    "hard": 15
}
COIN_PENALTY = 2  # Penalty for missing a task
WELCOME_IMAGE = "submissions/welcome.jpg"
SUPPORTED_LANGUAGES = ["uz", "en"]