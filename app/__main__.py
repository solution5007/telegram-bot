#main.py
"""Точка входа: python -m app"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.config import settings
from app.database import init_db, close_db
from app.panel import PanelAPI

# Красиво импортируем все наши разделенные роутеры
from app.handlers import user, payments, admin, admin_payments

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

    # Регистрация роутеров (СТРОГО ПО ОДНОМУ РАЗУ)
    # Порядок имеет значение: сначала админка, потом юзерские функции
    # ПРАВИЛЬНЫЙ ПОРЯДОК:
    dp.include_router(admin.router)
    dp.include_router(admin_payments.router) 
    dp.include_router(payments.router)
    dp.include_router(user.router)
      
  # Middleware-like: прокидываем panel и bot во все хендлеры через kwargs
    dp["panel"] = panel
    dp["bot"] = bot

    await init_db()
    
    # ЛОГИН В ПАНЕЛЬ ДО ЗАПУСКА БОТА
    logger.info("Логинюсь в панель...")
    session = await panel._ensure_session()
    if not session:
        logger.error("Не удалось подключиться к панели. Проверьте настройки config.py")
        return
    logger.info("Панель готова к работе!")
    
    logger.info("Бот запущен и готов к работе!")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await panel.close()
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")