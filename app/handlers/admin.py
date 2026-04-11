#admin.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import html
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.panel import PanelAPI
from app import database as db
from app.config import settings
from app.keyboards import admin_menu
from app.filters.is_admin import IsAdmin
from app.vpn_monitor.detect_anomalies import detect_anomalies
import json


router = Router(name="admin_panel")
logger = logging.getLogger(__name__)

router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

@router.message(Command("admin"))
async def admin_command(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Открыть панель", callback_data="admin_menu"))
    await message.answer("Добро пожаловать в центр управления!", reply_markup=builder.as_markup())

@router.callback_query(F.data == "admin_menu")
async def on_admin_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("<b>Админ Панель</b>\nВыберите действие:", parse_mode="HTML", reply_markup=admin_menu())

@router.callback_query(F.data == "show_anomalies")
async def handle_show_anomalies(callback: types.CallbackQuery):
    """Запускает анализ аномалий в отдельном потоке и выводит результаты."""
    await callback.answer("⏳ Анализирую метрики сервера...")
    
    try:
        # Запускаем блокирующую функцию в отдельном потоке
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            ThreadPoolExecutor(max_workers=1),
            detect_anomalies
        )
        
        # Отправляем результат в чат
        await callback.message.answer(
            result,
            parse_mode="HTML",
            reply_markup=admin_menu()
        )
    except Exception as e:
        logger.error(f"Ошибка анализа аномалий: {e}")
        await callback.message.answer(
            f"❌ Ошибка при анализе аномалий: {str(e)[:200]}",
            parse_mode="HTML",
            reply_markup=admin_menu()
        )
        
@router.callback_query(F.data == "admin_users")
async def on_show_all_users(callback: types.CallbackQuery, panel: PanelAPI):
    await callback.answer("Загружаю список...")

    # 1. Ручной запрос к API панели (заменяет метод в panel.py)
    url = f"{settings.panel_url}/panel/api/inbounds/list"
    
    try:
            # Вызываем созданный нами метод
            data = await panel.get_inbounds() 
            
            if not data.get("success"):
                await callback.message.edit_text(f"❌ Ошибка панели: {data.get('msg')}", reply_markup=admin_menu())
                return
                
            all_clients = []
            
            # Парсим входящие подключения и достаем юзеров
            for inbound in data.get("obj", []):
                # Тут используем другое имя переменной (inbound_settings), 
                # чтобы не конфликтовать с глобальным settings
                inbound_settings = json.loads(inbound.get("settings", "{}")) 
                clients = inbound_settings.get("clients", [])
                for client in clients:
                    all_clients.append(client)
    
            if not all_clients:
                await callback.message.edit_text("👤 Пользователей в панели пока нет.", reply_markup=admin_menu())
                return
            
        # ... дальше твой код по выводу списка юзеров

            # 2. Формируем текст
            text = "👤 <b>Список всех пользователей:</b>\n\n"
            for client in all_clients:
                email = client.get("email", "Без имени")
                # Проверяем лимит трафика (если 0 — значит безлимит)
                total_limit = client.get("total", 0)
                limit_str = f" / {round(total_limit / (1024**3), 1)} GB" if total_limit > 0 else ""
                
                # Потребленный трафик
                used = (client.get("up", 0) + client.get("down", 0)) / (1024**3)
                
                status = "✅" if client.get("enable") else "❌"
                text += f"{status} <code>{email}</code> | {round(used, 2)}{limit_str}\n"

            # 3. Отправляем результат
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu())

    except Exception as e:
        logger.error(f"Ошибка при получении списка юзеров: {e}")
        await callback.message.edit_text(f"❌ Произошла ошибка: {e}", reply_markup=admin_menu())