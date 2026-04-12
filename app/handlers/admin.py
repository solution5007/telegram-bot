#admin.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import html
import logging
import asyncio
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from app.panel import PanelAPI
from app import database as db
from app.config import settings
from app.keyboards import admin_menu
from app.filters.is_admin import IsAdmin
from app.vpn_monitor.detect_anomalies import detect_anomalies


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
    """Отправляет список всех активных пользователей из панели."""
    await callback.answer("⏳ Загружаю список...")

    try:
        # Получаем список инбаундов с клиентами
        data = await panel.get_inbounds()
        
        if not data.get("success"):
            error_msg = f"Ошибка панели: {data.get('msg', 'Unknown error')}"
            await _safe_edit_or_send(callback, error_msg, admin_menu())
            return
        
        # Собираем всех клиентов со всех инбаундов
        all_clients = []
        for inbound in data.get("obj", []):
            inbound_settings = json.loads(inbound.get("settings", "{}"))
            clients = inbound_settings.get("clients", [])
            all_clients.extend(clients)
        
        if not all_clients:
            await _safe_edit_or_send(callback, "👤 Пользователей в панели пока нет.", admin_menu())
            return
        
        # Сортируем по email для консистентности
        all_clients.sort(key=lambda x: x.get("email", ""))
        
        # Формируем текст со статистикой
        text = f"<b>Список всех пользователей ({len(all_clients)}):</b>\n\n"
        
        for client in all_clients:
            email = client.get("email", "Без имени")
            
            # Проверяем лимит трафика (если 0 — значит безлимит)
            total_limit = client.get("total", 0)
            limit_str = f" / {round(total_limit / (1024**3), 1)} GB" if total_limit > 0 else " (∞)"
            
            # Потребленный трафик
            up = client.get("up", 0) / (1024**3)
            down = client.get("down", 0) / (1024**3)
            used = up + down
            
            # Статус активности
            status = "✅" if client.get("enable") else "❌"
            
            # Информация об истечении (если есть)
            expire_time = client.get("expiryTime", 0)
            expire_str = ""
            if expire_time > 0:
                expire_date = datetime.fromtimestamp(expire_time / 1000)
                expire_str = f" | ⏰ {expire_date.strftime('%d.%m.%Y')}"
            
            text += f"{status} <code>{email}</code> | {round(used, 2)}{limit_str}{expire_str}\n"
        
        # Отправляем результат безопасно
        await _safe_edit_or_send(callback, text, admin_menu())

    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            # Если сообщение не изменилось, просто отвечаем через answer
            logger.info("Список пользователей не изменился, отправляю уведомление")
            await callback.answer("Список пользователей не изменился", show_alert=True)
        else:
            logger.error(f"Ошибка Telegram API: {e}")
            try:
                await callback.message.answer(
                    f"Ошибка Telegram: {str(e)[:100]}",
                    parse_mode="HTML",
                    reply_markup=admin_menu()
                )
            except Exception as ex:
                logger.error(f"Не удалось отправить сообщение об ошибке: {ex}")
                await callback.answer("Произошла ошибка", show_alert=True)
    
    except Exception as e:
        logger.error(f"Ошибка при получении списка юзеров: {e}", exc_info=True)
        try:
            await _safe_edit_or_send(
                callback,
                f"Ошибка при загрузке: {str(e)[:150]}",
                admin_menu()
            )
        except Exception as ex:
            logger.error(f"Не удалось отправить сообщение об ошибке: {ex}")
            await callback.answer("Произошла ошибка", show_alert=True)


async def _safe_edit_or_send(callback: types.CallbackQuery, text: str, reply_markup=None):
    """Безопасно редактирует сообщение, или отправляет новое если контент одинаков."""
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            # Если сообщение не изменилось, отправляем новое
            logger.debug("Сообщение не изменилось, отправляю новое")
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            # Для других ошибок редактирования - пробуем отправить как новое
            logger.warning(f"Ошибка редактирования: {e}, отправляю как новое сообщение")
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )