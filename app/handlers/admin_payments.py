"""Администраторские обработчики для управления платежами."""

from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import logging
from datetime import datetime, timedelta

from app import database as db
from app.panel import PanelAPI
from app.utils.generate_vless import generate_vless_link
from app.filters.is_admin import IsAdmin
from app.keyboards import approve_reject_payment, admin_menu

router = Router(name="admin_payments")
logger = logging.getLogger(__name__)

PAYMENTS_PER_PAGE = 5

router.callback_query.filter(IsAdmin())


@router.callback_query(F.data.startswith("admin_payments_"))
async def show_payments_list(callback: types.CallbackQuery):
    """Показывает список заявок на оплату с пагинацией."""
    await callback.answer()
    
    try:
        # Извлекаем номер страницы
        page = int(callback.data.replace("admin_payments_", ""))
        
        # Получаем все заявки
        pending_payments = await db.get_pending_payments()
        
        if not pending_payments:
            text = "📭 <b>Нет заявок на оплату</b>\n\nВсе заявки обработаны или отсутствуют."
            await _safe_edit_or_send(callback, text, admin_menu())
            return
        
        # Сортируем по дате (новые сверху)
        pending_payments.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
        
        # Пагинация
        total_pages = (len(pending_payments) + PAYMENTS_PER_PAGE - 1) // PAYMENTS_PER_PAGE
        if page >= total_pages:
            page = total_pages - 1
        
        start_idx = page * PAYMENTS_PER_PAGE
        end_idx = start_idx + PAYMENTS_PER_PAGE
        current_payments = pending_payments[start_idx:end_idx]
        
        # Формируем текст со списком заявок
        text = f"📋 <b>Заявки на оплату ({len(pending_payments)} всего)</b>\n\n"
        text += f"📄 Страница {page + 1}/{total_pages}\n\n"
        
        # Добавляем каждую заявку как кнопку
        builder = InlineKeyboardBuilder()
        
        for payment_id, payment in current_payments:
            created_at = payment.get("created_at", "N/A")
            status_emoji = "⏳"
            
            # Текст кнопки: ID платежа и дата
            btn_text = f"{status_emoji} #{payment_id[:8]}... | {created_at[:10]}"
            builder.row(types.InlineKeyboardButton(
                text=btn_text,
                callback_data=f"payment_detail_{payment_id}"
            ))
        
        # Добавляем кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_payments_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(types.InlineKeyboardButton(text="Далее ▶️", callback_data=f"admin_payments_{page + 1}"))
        
        if nav_buttons:
            builder.row(*nav_buttons)
        
        # Кнопка возврата в меню
        builder.row(types.InlineKeyboardButton(text="Назад в админ-панель", callback_data="admin_menu"))
        
        await _safe_edit_or_send(callback, text, builder.as_markup())
        
    except Exception as e:
        logger.error(f"Ошибка при показе списка заявок: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки списка", show_alert=True)


@router.callback_query(F.data.startswith("payment_detail_"))
async def show_payment_detail(callback: types.CallbackQuery):
    """Показывает детали конкретной заявки и позволяет одобрить или отклонить."""
    await callback.answer()
    
    try:
        payment_id = callback.data.replace("payment_detail_", "")
        payment = await db.get_payment_request(payment_id)
        
        if not payment:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        
        # Получаем информацию о пользователе
        user = await db.get_user(payment["tg_id"])
        username = user.get("username", "unknown") if user else "unknown"
        
        # Формируем детальную информацию
        created_at = payment.get("created_at", "N/A")
        text = f"""💳 <b>Деталь заявки на оплату</b>

📊 <b>ID:</b> <code>{payment_id}</code>
👤 <b>Пользователь:</b> {username} (ID: {payment['tg_id']})
⏰ <b>Дата:</b> {created_at}
📸 <b>Чек:</b> {'Прикреплен' if payment.get('screenshot_file_id') else 'Отсутствует'}
ℹ️ <b>Заметка:</b> {payment.get('admin_note', 'Нет')}

Выберите действие:"""
        
        # Если есть скриншот, показываем его
        if payment.get("screenshot_file_id"):
            try:
                await callback.message.delete()
                await callback.message.answer_photo(
                    photo=payment["screenshot_file_id"],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=approve_reject_payment(payment_id)
                )
            except Exception as e:
                logger.debug(f"Не удалось отправить фото: {e}, отправляю как текст")
                await _safe_edit_or_send(callback, text, approve_reject_payment(payment_id))
        else:
            await _safe_edit_or_send(callback, text, approve_reject_payment(payment_id))
            
    except Exception as e:
        logger.error(f"Ошибка при показе деталей заявки: {e}", exc_info=True)
        await callback.answer("❌ Ошибка загрузки деталей", show_alert=True)


@router.callback_query(F.data.startswith("approve_payment_"))
async def on_approve_payment(callback: types.CallbackQuery, panel: PanelAPI):
    """Одобрить платёж и создать клиента в панели."""
    await callback.answer()
    
    # Извлекаем ID платежа
    payment_id = callback.data.replace("approve_payment_", "").replace(":", "")
    payment = await db.get_payment_request(payment_id)
    
    if not payment:
        await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
        return

    async def safe_edit(text: str):
        """Безопасно редактирует сообщение (текст или подпись фото)."""
        try:
            await callback.message.edit_text(text, parse_mode="HTML")
        except TelegramBadRequest:
            try:
                await callback.message.edit_caption(caption=text, parse_mode="HTML")
            except TelegramBadRequest:
                # Если не получается редактировать, отправляем новое сообщение
                await callback.message.answer(text, parse_mode="HTML")

    try:
        request_type = payment.get("type", "new")
        
        if request_type == "renewal":
            await safe_edit("⏳ Обрабатываю продление подписки...")
        else:
            await safe_edit("⏳ Создаю VPN-клиента в панели...")

        user = await db.get_user(payment["tg_id"])
        username = user.get("username", f"user_{payment['tg_id']}") if user else f"user_{payment['tg_id']}"
        
        period = payment.get("period", 1)
        
        if request_type == "renewal":
            # ── ПРОДЛЕНИЕ ПОДПИСКИ ──
            if not user:
                await safe_edit(f"❌ <b>Ошибка:</b> Пользователь не найден.\nID: <code>{payment_id}</code>")
                return
            
            uuid_str = user.get("uuid")
            email = user.get("email")
            
            if not uuid_str or not email:
                await safe_edit(f"❌ <b>Ошибка:</b> Не удалось найти данные клиента.\nID: <code>{payment_id}</code>")
                return
            
            # Рассчитываем новый expiry_time (продление текущего или с сегодня)
            if period == 0:
                new_expiry_ms = 0
                new_expiry_iso = 0
            else:
                days = period * 30
                expiry_datetime = datetime.now() + timedelta(days=days)
                new_expiry_ms = int(expiry_datetime.timestamp() * 1000)
                new_expiry_iso = expiry_datetime.isoformat()
            
            # Обновляем expiry time в панели
            if not await panel.update_client_expiry(email, new_expiry_ms):
                logger.warning(f"Не удалось обновить expiry time для {email}")
            
            # Сохраняем новый expiry_date в БД
            await db.upsert_user(payment["tg_id"], username, uuid_str, email, status="active", expiry_time=new_expiry_iso)
            await db.approve_payment(payment_id, "Одобрено администратором")
            
            # Уведомляем пользователя о продлении
            try:
                if period == 0:
                    message_text = "✅ <b>Подписка продлена!</b>\n\nТеперь у вас безлимитный доступ ♾️"
                else:
                    message_text = f"✅ <b>Подписка продлена!</b>\n\nНовый срок: {period} месяц{'а' if period == 1 else 'ев'}\nДо: {new_expiry_iso.split('T')[0]}"
                
                await callback.bot.send_message(
                    payment["tg_id"],
                    message_text,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о продлении: {e}")
            
            await safe_edit(f"✅ Заявка на продление <code>{payment_id}</code> одобрена!")
            
        else:
            # ── НОВАЯ ПОДПИСКА ──
            if period == 0:
                expiry_ms = 0
                expiry_iso = 0
            else:
                days = period * 30
                expiry_datetime = datetime.now() + timedelta(days=days)
                expiry_ms = int(expiry_datetime.timestamp() * 1000)
                expiry_iso = expiry_datetime.isoformat()

            # Создаем клиента в панели сразу с нужным expiry_time
            uuid_str, email = await panel.add_client(payment["tg_id"], username, expiry_time=expiry_ms)
            
            if not uuid_str:
                if user and user.get("uuid"):
                    uuid_str = user["uuid"]
                    email = user["email"]
                else:
                    await safe_edit(f"❌ <b>Ошибка:</b> Не удалось создать клиента в панели.\nID: <code>{payment_id}</code>")
                    return

            # Если клиент создан, сохраняем expiry_date в БД
            await db.upsert_user(payment["tg_id"], username, uuid_str, email, status="active", expiry_time=expiry_iso)
            await db.approve_payment(payment_id, "Одобрено администратором")
            
            # Отправляем VPN ссылку пользователю
            try:
                link = generate_vless_link(uuid_str, email)
                await callback.bot.send_message(
                    payment["tg_id"], 
                    f"✅ <b>Ваш платеж одобрен!</b>\n\nVPN готов!\n\n<code>{link}</code>", 
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки VPN ссылки пользователю: {e}")
            
            await safe_edit(f"✅ Заявка <code>{payment_id}</code> одобрена и активирована!")
        
    except Exception as e:
        logger.error(f"Ошибка при одобрении платежа: {e}", exc_info=True)
        await safe_edit(f"❌ Ошибка при одобрении: {str(e)[:100]}")


@router.callback_query(F.data.startswith("reject_payment_"))
async def on_reject_payment(callback: types.CallbackQuery):
    """Отклонить платёж и полностью удалить данные."""
    await callback.answer()
    
    try:
        payment_id = callback.data.replace("reject_payment_", "").replace(":", "")
        payment = await db.get_payment_request(payment_id)
        
        if not payment:
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return

        # 1. Сначала уведомляем пользователя
        try:
            await callback.bot.send_message(
                payment["tg_id"],
                "❌ <b>Ваш платеж отклонен.</b>\nДанные удалены. Попробуйте отправить корректный чек заново.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя: {e}")
        
        # 2. Удаляем из БД
        await db.reject_payment(payment_id, "Отклонено администратором")
        await db.delete_payment_request(payment_id)
        
        # 3. Обновляем сообщение админа (убираем кнопки)
        final_text = f"❌ Заявка <code>{payment_id}</code> отклонена и удалена."
        
        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=final_text, parse_mode="HTML")
            else:
                await callback.message.edit_text(final_text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение админа: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при отклонении платежа: {e}", exc_info=True)
        await callback.answer("❌ Ошибка при отклонении платежа", show_alert=True)


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
    except Exception as e:
        logger.error(f"Ошибка при редактировании/отправке сообщения: {e}")
        try:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception as ex:
            logger.error(f"Не удалось отправить сообщение: {ex}")
