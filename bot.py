import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.config import settings
from app.panel import PanelAPI



logger = logging.getLogger(__name__)
bot = Bot(token=settings.bot_token)
dp = Dispatcher()
panel = PanelAPI()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect('vpn_bot.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT,
            uuid TEXT,
            email TEXT
        )''')
        await db.commit()
    logger.info("База данных инициализирована.")

# --- ГЕНЕРАТОР ССЫЛОК ---
def generate_vless_link(uuid_str, email):
    # Достаем IP сервера из панели (убираем https:// и порт)
    server_ip = settings.panel_url.replace("https://", "").replace("http://", "").split(":")[0]
    server_port = "443" # Порт VLESS Reality
    
    link = (f"vless://{uuid_str}@{server_ip}:{server_port}"
            f"?security=reality&sni={settings.vless_sni}&fp=chrome&pbk={settings.vless_public_key}"
            f"&sid={settings.vless_sid}&type=tcp&flow=xtls-rprx-vision&headerType=none#{email}")
    return link

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} нажал /start")
    
    async with aiosqlite.connect('vpn_bot.db') as db:
        async with db.execute('SELECT * FROM users WHERE tg_id = ?', (message.from_user.id,)) as cursor:
            user = await cursor.fetchone()
    
    builder = InlineKeyboardBuilder()
    
    if user:
        builder.row(types.InlineKeyboardButton(txt="Мой кабинет", callback_data="profile"))
        text = "С возвращением! Управление твоим VPN ниже "
    else:
        builder.row(types.InlineKeyboardButton(text="Создать VPN", callback_data="create_vpn"))
        text = "Привет! У тебя еще нет VPN-подключения. Нажми кнопку ниже, чтобы создать."
        
    await message.answer(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "create_vpn")
async def process_create_vpn(callback: types.CallbackQuery):
    await callback.message.edit_text("Подключаюсь к серверу и генерирую ключ...")
    
    # Создаем клиента в панели
    uuid_str, email = await panel.add_client(callback.from_user.id, callback.from_user.username)
    
    if not uuid_str:
        await callback.message.edit_text("Ошибка при создании VPN. Сервер недоступен или настройки неверны.")
        return

    # Сохраняем в БД
    async with aiosqlite.connect('vpn_bot.db') as db:
        await db.execute('INSERT OR REPLACE INTO users (tg_id, username, uuid, email) VALUES (?, ?, ?, ?)',
                         (callback.from_user.id, callback.from_user.username, uuid_str, email))
        await db.commit()
    
    link = generate_vless_link(uuid_str, email)
    
    # Меняем клавиатуру на кнопку "В кабинет"
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👤 Мой кабинет", callback_data="profile"))
    
    await callback.message.edit_text(
        f"Твой VPN успешно создан!\n\n"
        f"Вот твоя персональная ссылка для подключения (скопируй её кликом):\n\n"
        f"`{link}`\n\n"
        f"Используйте её в любом клиенте для создания подключения.",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "profile")
async def process_profile(callback: types.CallbackQuery):
    await callback.message.edit_text("Загружаю статистику...")
    
    async with aiosqlite.connect('vpn_bot.db') as db:
        async with db.execute('SELECT uuid, email FROM users WHERE tg_id = ?', (callback.from_user.id,)) as cursor:
            user = await cursor.fetchone()
            
    if not user:
        await callback.message.edit_text("Пользователь не найден в базе.")
        return

    uuid_str, email = user[0], user[1]
    
    # Запрашиваем трафик
    up, down = await panel.get_client_traffic(email)
    total_gb = round((up + down) / (1024**3), 2)
    
    link = generate_vless_link(uuid_str, email)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Обновить", callback_data="profile"))
    
    await callback.message.edit_text(
        f"Личный кабинет\n\n"
        f"Пользователь: {email}\n"
        f"Потрачено трафика: {total_gb} GB\n\n"
        f"Твой ключ:\n`{link}`",
        parse_mode="Markdown",
        reply_markup=builder.as_markup()    
    )

async def main():
    await init_db()
    
    # ✅ ЛОГИН В ПАНЕЛЬ ДО ЗАПУСКА БОТА
    logger.info("Логинюсь в панель...")
    session = await panel._ensure_session()
    if not session:
        logger.error("Не удалось подключиться к панели. Проверьте настройки .env")
        return
    logger.info("Панель готова к работе!")
    
    logger.info("Бот запущен и готов к работе!")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Корректно закрываем сессию с панелью
        if panel._session:
            await panel._session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")