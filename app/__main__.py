"""Точка входа: ``python -m app``."""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import settings
from app.database import init_db, close_db
from app.handlers.user import router as user_router
from app.handlers.payments import router as payments_router
from app.panel import PanelAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Инициализация
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    panel = PanelAPI()

    # Регистрация роутеров
    dp.include_router(payments_router)
    dp.include_router(user_router)

    # Middleware‑like: прокидываем panel и bot во все хендлеры через kwargs
    dp["panel"] = panel
    dp["bot"] = bot

    await init_db()
    
    # ✅ ЛОГИН В ПАНЕЛЬ ДО ЗАПУСКА БОТА
    logger.info("🔐 Логинюсь в панель...")
    session = await panel._ensure_session()
    if not session:
        logger.error("❌ Не удалось подключиться к панели. Проверьте настройки config.py")
        return
    logger.info("✅ Панель готова к работе!")
    
    logger.info("🚀 Бот запущен и готов к работе!")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await panel.close()
        await close_db()
        await bot.session.close()
        logger.info("👋 Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
