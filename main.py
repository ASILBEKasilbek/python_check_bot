import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from database.db import init_db
from scheduler.jobs import check_deadlines, send_daily_problems
from handlers.admin import admin_router
from handlers.user import user_router
from handlers.common import common_router
from config.settings import TIMEZONE, BOT_TOKEN  # BOT_TOKEN ni settings.py dan import qilamiz

# Configure logging
logging.basicConfig(level=logging.INFO)

async def main():
    # Initialize database
    init_db()
    
    # Initialize bot
    bot = Bot(token=BOT_TOKEN)
    
    # Initialize dispatcher with bot
    dp = Dispatcher(storage=MemoryStorage())
    
    # Include routers
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    
    # Setup scheduler
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(check_deadlines, "interval", minutes=30)
    scheduler.add_job(send_daily_problems, CronTrigger(hour=0, minute=0, second=0))
    scheduler.start()
    
    # Start polling
    await dp.start_polling(bot)  # bot ni ham beramiz

if __name__ == "__main__":
    asyncio.run(main())
