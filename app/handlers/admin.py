#admin.py
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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

# Определяем состояния для FSM (конечный автомат)
class NotificationStates(StatesGroup):
    """Состояния для отправки оповещений всем пользователям."""
    waiting_for_message = State()  # Ожидаем ввода сообщения от админа

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
        
@router.callback_query(F.data == "send_notification")
async def handle_send_notification(callback: types.CallbackQuery, state: FSMContext):
    """Запускает процесс отправки оповещения всем пользователям."""
    await callback.answer()
    
    # Предлагаем админу написать сообщение
    cancel_btn = types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_notification")
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[cancel_btn]])
    
    await callback.message.answer(
        "📝 <b>Отправить оповещение всем пользователям</b>\n\n"
        "Напишите сообщение, которое будет отправлено всем пользователям:\n\n"
        "<i>(Отмена: нажмите кнопку ниже или напишите /cancel)</i>",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    
    # Переходим в состояние ожидания сообщения
    await state.set_state(NotificationStates.waiting_for_message)


@router.callback_query(F.data == "cancel_notification", StateFilter(NotificationStates.waiting_for_message))
async def cancel_notification(callback: types.CallbackQuery, state: FSMContext):
    """Отмена отправки оповещения."""
    await callback.answer("❌ Отправка отменена", show_alert=True)
    await state.clear()
    
    # Показываем админ меню
    await callback.message.edit_text(
        "<b>Админ Панель</b>\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


@router.message(Command("cancel"), StateFilter(NotificationStates.waiting_for_message))
async def cancel_notification_command(message: types.Message, state: FSMContext):
    """Отмена отправки оповещения через команду /cancel."""
    await message.answer("❌ Отправка отменена", reply_markup=admin_menu())
    await state.clear()


@router.message(StateFilter(NotificationStates.waiting_for_message))
async def process_notification_message(message: types.Message, state: FSMContext):
    """Обрабатывает сообщение администратора и отправляет его всем пользователям."""
    
    # Проверяем что это текстовое сообщение
    if not message.text:
        await message.answer("❌ Пожалуйста, напишите текстовое сообщение.")
        return
    
    notification_text = message.text
    
    # Даем обратную связь админу
    status_message = await message.answer(
        "⏳ <b>Отправляю оповещение...</b>\n\n"
        "Статус: инициализация...",
        parse_mode="HTML"
    )
    
    try:
        # Получаем всех пользователей из БД
        all_users = await db.get_all_users()
        
        if not all_users:
            await status_message.edit_text(
                "⚠️ <b>Нет зарегистрированных пользователей</b>",
                parse_mode="HTML"
            )
            await state.clear()
            return
        
        # Статистика отправки
        successful = 0
        failed = 0
        failed_users = []
        
        # Отправляем сообщение каждому пользователю
        for user_data in all_users:
            try:
                tg_id = user_data.get("tg_id")
                username = user_data.get("username", "Unknown")
                
                if not tg_id:
                    failed += 1
                    continue
                
                # Отправляем сообщение с красивым форматированием
                await message.bot.send_message(
                    tg_id,
                    f"📢 <b>Оповещение от администратора:</b>\n\n{notification_text}",
                    parse_mode="HTML"
                )
                successful += 1
                
                # Обновляем статус каждые 5 отправок
                if (successful + failed) % 5 == 0:
                    await status_message.edit_text(
                        f"⏳ <b>Отправляю оповещение...</b>\n\n"
                        f"✅ Успешно: {successful}\n"
                        f"❌ Ошибок: {failed}\n"
                        f"📊 Всего: {len(all_users)}",
                        parse_mode="HTML"
                    )
                    
            except Exception as e:
                failed += 1
                tg_id = user_data.get("tg_id", "unknown")
                failed_users.append((tg_id, str(e)[:50]))
                logger.warning(f"Не удалось отправить сообщение пользователю {tg_id}: {e}")
        
        # Финальное сообщение со статистикой
        final_text = f"""✅ <b>Оповещение отправлено!</b>

📊 <b>Статистика отправки:</b>
✅ Успешно доставлено: <b>{successful}</b>
❌ Ошибок: <b>{failed}</b>
📈 Всего пользователей: <b>{len(all_users)}</b>

<i>Процент успеха: {round((successful / len(all_users) * 100), 1)}%</i>"""
        
        # Если были ошибки, добавляем информацию
        if failed_users and len(failed_users) <= 10:
            final_text += "\n\n<b>Пользователи, к которым не удалось доставить:</b>\n"
            for user_id, error in failed_users[:10]:
                final_text += f"• ID: {user_id} ({error})\n"
        
        await status_message.edit_text(final_text, parse_mode="HTML")
        
        # Логируем отправку
        logger.info(f"Администратор отправил оповещение {successful} пользователям (ошибок: {failed})")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке оповещений: {e}", exc_info=True)
        await status_message.edit_text(
            f"❌ <b>Ошибка при отправке:</b>\n\n{str(e)[:200]}",
            parse_mode="HTML"
        )
    
    finally:
        # Выходим из состояния
        await state.clear()

        
@router.callback_query(F.data == "admin_users")
async def on_show_all_users(callback: types.CallbackQuery, panel: PanelAPI):
    """Отправляет список всех активных пользователей из панели."""
    await callback.answer("⏳ Загружаю список...")

    try:
        # Получаем список инбаундов с клиентами
        logger.info("📤 Запрашиваю список всех пользователей из панели...")
        data = await panel.get_inbounds()
        
        if not data.get("success"):
            error_msg = f"❌ Ошибка панели: {data.get('msg', 'Unknown error')}"
            logger.error(f"Ошибка при получении инбаундов: {error_msg}")
            await _safe_edit_or_send(callback, error_msg, admin_menu())
            return
        
        # Собираем всех клиентов со всех инбаундов
        all_clients = []
        obj_list = data.get("obj", [])
        logger.info(f"✅ Получено {len(obj_list)} инбаундов")
        
        for inbound in obj_list:
            try:
                inbound_settings = json.loads(inbound.get("settings", "{}"))
                clients = inbound_settings.get("clients", [])
                all_clients.extend(clients)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Ошибка парсинга settings для инбаунда: {e}")
                continue
        
        if not all_clients:
            logger.warning("⚠️ Пользователей в панели не найдено")
            await _safe_edit_or_send(callback, "👤 Пользователей в панели пока нет.", admin_menu())
            return
        
        logger.info(f"✅ Найдено {len(all_clients)} клиентов в панели")
        
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