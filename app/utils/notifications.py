#notifications.py
from aiogram import Bot, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging

from app import database as db
from app.config import settings

logger = logging.getLogger(__name__)

async def notify_admin_about_payment(bot: Bot, payment_id: str, tg_id: int, username: str | None) -> None:
    """Отправить уведомление администратору о новой заявке."""
    try:
        payment = await db.get_payment_request(payment_id)
        if not payment:
            return
        
        username = username or "unknown"
        
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="Одобрить", callback_data=f"approve_payment_{payment_id}"),
            types.InlineKeyboardButton(text="Отклонить", callback_data=f"reject_payment_{payment_id}")
        )
        
        period = payment.get("period", 1)
        period_text = f"{period} месяц" + ("ов" if period != 1 else "")
        text = (
            f"🟢 <b>Новая заявка на оплату</b>\n\n"
            f"Пользователь: @{username}\n"
            f"ID: <code>{tg_id}</code>\n"
            f"Заявка: <code>{payment_id}</code>\n"
            f"Период: {period_text}\n"
            f"Дата: {payment['created_at'][:19]}\n"
        )
        
        await bot.send_photo(
            settings.admin_id,
            photo=payment["screenshot_file_id"],
            caption=text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")