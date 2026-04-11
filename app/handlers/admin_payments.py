from aiogram import Router, F, types
import logging

from app import database as db
from app.panel import PanelAPI  # Импорт класса
from app.utils.generate_vless import generate_vless_link
from app.filters.is_admin import IsAdmin

router = Router(name="admin_payments")
logger = logging.getLogger(__name__)

# Создаем объект панели здесь, чтобы он был доступен в хендлерах
panel = PanelAPI() 

router.callback_query.filter(IsAdmin())

@router.callback_query(F.data.startswith("approve_payment_"))
async def on_approve_payment(callback: types.CallbackQuery):
    """Одобрить платёж и создать клиента в панели."""
    await callback.answer()
    
    # Извлекаем ID (убираем префикс и возможные двоеточия)
    payment_id = callback.data.replace("approve_payment_", "").replace(":", "")
    payment = await db.get_payment_request(payment_id)
    
    if not payment:
        await callback.answer("Заявка не найдена или уже обработана", show_alert=True)
        return

    async def safe_edit(text: str):
        try:
            await callback.message.edit_text(text, parse_mode="HTML")
        except Exception:
            await callback.message.edit_caption(caption=text, parse_mode="HTML")

    await safe_edit("⏳ Создаю VPN-клиента в панели...")

    user = await db.get_user(payment["tg_id"])
    username = user.get("username", f"user_{payment['tg_id']}") if user else f"user_{payment['tg_id']}"
    
    # Теперь 'panel' определен выше
    uuid_str, email = await panel.add_client(payment["tg_id"], username)
    
    if not uuid_str:
        if user and user.get("uuid"):
            uuid_str = user["uuid"]
            email = user["email"]
        else:
            await safe_edit(f"❌ <b>Ошибка:</b> Не удалось создать клиента.\nID: <code>{payment_id}</code>")
            return
        
    await db.upsert_user(payment["tg_id"], username, uuid_str, email, status="active")
    await db.approve_payment(payment_id, "Одобрено администратором")
    
    try:
        link = generate_vless_link(uuid_str, email)
        await callback.bot.send_message(
            payment["tg_id"], 
            f"✅ <b>Ваш платеж одобрен!</b>\n\nVPN готов!\n\n<code>{link}</code>", 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки пользователю: {e}")
    
    await safe_edit(f"✅ Заявка <code>{payment_id}</code> одобрена!")


@router.callback_query(F.data.startswith("reject_payment_"))
async def on_reject_payment(callback: types.CallbackQuery):
    """Отклонить платёж и полностью удалить данные."""
    await callback.answer()
    
    payment_id = callback.data.replace("reject_payment_", "").replace(":", "")
    payment = await db.get_payment_request(payment_id)
    
    if not payment:
        return

    # 1. Сначала удаляем из БД
    await db.reject_payment(payment_id, "Отклонено администратором")
    await db.delete_payment_request(payment_id)
    
    # 2. Уведомляем пользователя
    try:
        await callback.bot.send_message(
            payment["tg_id"],
            "❌ <b>Ваш платеж отклонен.</b>\nДанные удалены. Попробуйте отправить корректный чек заново.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")
    
    # 3. Обновляем сообщение админа (убираем кнопки)
    final_text = f"❌ Заявка <code>{payment_id}</code> отклонена и удалена."
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=final_text, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=final_text, parse_mode="HTML")
    except Exception as e:
      logger.error(f"Ошибка обновления сообщения админа: {e}")