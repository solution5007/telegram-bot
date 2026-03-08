"""Обработчики платежей и системы оплаты."""

from aiogram import Router, types, F, Bot
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging

from app import database as db
from app.config import settings
from app.keyboards import (
    buy_vpn_menu, payment_confirmation_menu, admin_menu,
    admin_payments_pagination, approve_reject_payment, main_menu
)
from app.panel import PanelAPI
from app.utils import generate_vless_link

router = Router(name="payments")
logger = logging.getLogger(__name__)

# Реквизиты из config
CARD_NUMBER = getattr(settings, 'card_number', '5500 0000 0000 0000')  # Пример
PAYMENT_AMOUNT = getattr(settings, 'payment_amount', '150')  # В рублях

class PaymentStates(StatesGroup):
    """Состояния для системы платежей."""
    waiting_for_screenshot = State()
    waiting_for_payment_confirmation = State()


@router.callback_query(F.data == "buy_vpn")
async def on_buy_vpn(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Начало процесса покупки VPN."""
    await callback.message.edit_text(
        f"VPN Подписка\n\n"
        f"Стоимость: {PAYMENT_AMOUNT} руб\n"
        f"Срок: 1 месяц\n\n"
        f"Реквизиты платежа:\n"
        f"<code>{CARD_NUMBER}</code>\n\n"
        f"1. Оплатите по карте выше\n"
        f"2. Загрузите скриншот платежа\n"
        f"3. Нажмите кнопку ниже\n\n"
        f"После проверки администратором вам выдадут доступ.",
        parse_mode="HTML",
        reply_markup=buy_vpn_menu()
    )


@router.callback_query(F.data == "upload_payment")
async def on_upload_payment(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Запрос на загрузку скриншота платежа."""
    await state.set_state(PaymentStates.waiting_for_screenshot)
    await callback.message.edit_text(
        "Загрузите скриншот платежа\n\n"
        "Отправьте фото чека или скриншота с подтверждением платежа.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="buy_vpn")]
        ])
    )


@router.message(PaymentStates.waiting_for_screenshot)
async def on_screenshot_received(message: types.Message, state: FSMContext) -> None:
    """Получение скриншота платежа."""
    if not message.photo:
        await message.answer("Пожалуйста, отправьте фото/изображение.")
        return
    
    # Берем самое большое изображение
    photo = message.photo[-1]
    await state.update_data(screenshot_file_id=photo.file_id)
    await state.set_state(PaymentStates.waiting_for_payment_confirmation)
    
    await message.answer(
        "Скриншот получен!\n\n"
        "Нажмите подтверждение, чтобы отправить заявку на проверку.",
        reply_markup=payment_confirmation_menu()
    )


@router.callback_query(F.data == "confirm_payment", StateFilter(PaymentStates.waiting_for_payment_confirmation))
async def on_confirm_payment(callback: types.CallbackQuery, state: FSMContext, panel: PanelAPI) -> None:
    """Подтверждение платежа и создание заявки."""
    data = await state.get_data()
    screenshot_file_id = data.get("screenshot_file_id")
    
    if not screenshot_file_id:
        await callback.message.edit_text("Ошибка: скриншот не найден.")
        return
    
    # Создаем VPN клиента
    await callback.message.edit_text("Создаю VPN и отправляю заявку на проверку...")
    
    uuid_str, email = await panel.add_client(callback.from_user.id, callback.from_user.username)
    
    if not uuid_str:
        await callback.message.edit_text(
            "Ошибка при создании VPN. Попробуйте позже или свяжитесь с администратором."
        )
        await state.clear()
        return
    
    # Сохраняем пользователя в БД со статусом pending_payment
    await db.upsert_user(
        callback.from_user.id,
        callback.from_user.username,
        uuid_str,
        email,
        status="pending_payment"
    )
    
    # Создаем заявку на платёж
    payment_id = await db.create_payment_request(callback.from_user.id, screenshot_file_id)
    
    await callback.message.edit_text(
        f"Заявка создана!\n\n"
        f"ID заявки: <code>{payment_id}</code>\n\n"
        f"Ожидайте проверки администратора.\n\n"
        f"Вам придет уведомление когда заявка будет рассмотрена.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Главное меню", callback_data="main_menu")]
        ])
    )
    
    # Отправляем уведомление администратору
    await notify_admin_about_payment(callback.bot, payment_id, callback.from_user.id, callback.from_user.username)
    
    await state.clear()


# ── АДМИН КОМАНДЫ ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_menu")
async def on_admin_menu(callback: types.CallbackQuery) -> None:
    """Админ меню."""
    if callback.from_user.id != settings.admin_id:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "Админ Панель\n\n"
        "Выберите действие:",
        reply_markup=admin_menu()
    )


@router.callback_query(F.data.startswith("admin_payments"))
async def on_admin_payments(callback: types.CallbackQuery) -> None:
    """Список заявок на платежи."""
    if callback.from_user.id != settings.admin_id:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    # Парсим номер страницы
    page = 0
    if "_" in callback.data:
        try:
            page = int(callback.data.split("_")[2])
        except (IndexError, ValueError):
            page = 0
    
    payments = await db.get_pending_payments()
    
    if not payments:
        await callback.message.edit_text(
            "Заявок на оплату нет\n\nВсе платежи уже обработаны.",
            reply_markup=admin_menu()
        )
        return
    
    # Пагинация: 1 заявка на странице (чтобы вместились кнопки)
    page_size = 1
    start = page * page_size
    end = start + page_size
    page_payments = payments[start:end]
    
    if not page_payments:
        await callback.message.edit_text(
            "Заявок на оплату нет\n\nВсе платежи уже обработаны.",
            reply_markup=admin_menu()
        )
        return
    
    payment_id, payment = page_payments[0]
    user = await db.get_user(payment["tg_id"])
    username = user.get("username", "unknown") if user else "unknown"
    
    text = (
        f"Заявка на оплату (#{page + 1} из {len(payments)})\n\n"
        f"Пользователь: {username}\n"
        f"ID: {payment['tg_id']}\n"
        f"Дата: {payment['created_at'][:19]}\n\n"
        f"Выберите действие:"
    )
    
    # Создаем клавиатуру с кнопками
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Одобрить", callback_data=f"approve_payment_{payment_id}"),
        types.InlineKeyboardButton(text="Отклонить", callback_data=f"reject_payment_{payment_id}")
    )
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="Назад", callback_data=f"admin_payments_{page - 1}"))
    if (page + 1) * page_size < len(payments):
        nav_buttons.append(types.InlineKeyboardButton(text="Далее", callback_data=f"admin_payments_{page + 1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    builder.row(types.InlineKeyboardButton(text="Админ меню", callback_data="admin_menu"))
    
    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("approve_payment_"))
async def on_approve_payment(callback: types.CallbackQuery) -> None:
    """Одобрить платёж."""
    if callback.from_user.id != settings.admin_id:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    payment_id = callback.data.replace("approve_payment_", "")
    payment = await db.get_payment_request(payment_id)
    
    if not payment:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    
    # Одобряем платёж
    await db.approve_payment(payment_id, "Одобрено администратором")
    
    # Отправляем уведомление пользователю
    try:
        user = await db.get_user(payment["tg_id"])
        if user:
            link = generate_vless_link(user["uuid"], user["email"])
            await callback.bot.send_message(
                payment["tg_id"],
                f"Ваш платеж одобрен!\n\n"
                f"VPN готов к использованию!\n\n"
                f"Ваша ссылка:\n\n"
                f"<code>{link}</code>\n\n"
                f"Используйте её в любом клиенте для создания подключения.",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю: {e}")
    
    await callback.answer("Платеж одобрен!", show_alert=True)
    # Отправляем сообщение с уведомлением о следующей заявке
    await callback.bot.send_message(
        settings.admin_id,
        "Переход к следующей заявке..."
    )


@router.callback_query(F.data.startswith("reject_payment_"))
async def on_reject_payment(callback: types.CallbackQuery) -> None:
    """Отклонить платёж."""
    if callback.from_user.id != settings.admin_id:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    payment_id = callback.data.replace("reject_payment_", "")
    payment = await db.get_payment_request(payment_id)
    
    if not payment:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    
    # Отклоняем платёж
    await db.reject_payment(payment_id, "Отклонено администратором")
    
    # Отправляем уведомление пользователю
    try:
        await callback.bot.send_message(
            payment["tg_id"],
            f"Ваш платеж отклонен\n\n"
            f"Проверьте скриншот платежа и попробуйте отправить его заново.\n"
            f"Если у вас есть вопросы, напишите администратору."
        )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения пользователю: {e}")
    
    await callback.answer("Платеж отклонен!", show_alert=True)
    # Отправляем сообщение с уведомлением о следующей заявке
    await callback.bot.send_message(
        settings.admin_id,
        "Переход к следующей заявке..."
    )


@router.callback_query(F.data == "admin_users")
async def on_admin_users(callback: types.CallbackQuery) -> None:
    """Список всех пользователей."""
    if callback.from_user.id != settings.admin_id:
        await callback.answer("Доступ запрещен", show_alert=True)
        return
    
    users = await db.get_all_users()
    
    if not users:
        await callback.message.edit_text(
            "Пользователей нет",
            reply_markup=admin_menu()
        )
        return
    
    text = f"Все пользователи ({len(users)} всего)\n\n"
    
    for user in users[:20]:  # Показываем первых 20
        status_symbol = "OK" if user.get("status", "active") == "active" else "WAIT"
        text += (
            f"{status_symbol} {user.get('username', 'unknown')}\n"
            f"   ID: {user['tg_id']}\n"
            f"   Email: {user['email']}\n\n"
        )
    
    if len(users) > 20:
        text += f"... и еще {len(users) - 20}."
    
    await callback.message.edit_text(
        text,
        reply_markup=admin_menu()
    )


@router.message(F.text == "/admin")
async def admin_command(message: types.Message) -> None:
    """Команда /admin для входа в админ панель."""
    if message.from_user.id != settings.admin_id:
        await message.answer("Доступ запрещен")
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Админ Панель", callback_data="admin_menu"))
    
    await message.answer(
        "Добро пожаловать в админ панель!",
        reply_markup=builder.as_markup()
    )


# ── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ───────────────────────────────────────────────

async def notify_admin_about_payment(bot: Bot, payment_id: str, tg_id: int, username: str | None) -> None:
    """Отправить уведомление администратору о новой заявке."""
    try:
        payment = await db.get_payment_request(payment_id)
        if not payment:
            return
        
        username = username or "unknown"
        
        # Создаем кнопки для одобрения/отклонения
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="Одобрить", callback_data=f"approve_payment_{payment_id}"),
            types.InlineKeyboardButton(text="Отклонить", callback_data=f"reject_payment_{payment_id}")
        )
        
        text = (
            f"Новая заявка на оплату\n\n"
            f"{username}\n"
            f"ID: {tg_id}\n"
            f"Заявка: <code>{payment_id}</code>\n"
            f"{payment['created_at'][:19]}\n\n"
        )
        
        # Отправляем фото с кнопками
        await bot.send_photo(
            settings.admin_id,
            photo=payment["screenshot_file_id"],
            caption=text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")
