#payments.py
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import logging

from app import database as db
from app.config import settings
from app.keyboards import buy_vpn_menu, payment_confirmation_menu
from app.panel import PanelAPI
from app.utils.notifications import notify_admin_about_payment

router = Router(name="user_payments")
logger = logging.getLogger(__name__)

CARD_NUMBER = getattr(settings, 'card_number', '5500 0000 0000 0000')
PAYMENT_AMOUNT = getattr(settings, 'payment_amount', '150')

class PaymentStates(StatesGroup):
    choosing_period = State()
    waiting_for_screenshot = State()
    waiting_for_payment_confirmation = State()
    renewal_choosing_period = State()
    renewal_waiting_for_screenshot = State()
    renewal_waiting_for_payment_confirmation = State()

@router.callback_query(F.data == "buy_vpn")
async def on_buy_vpn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.choosing_period)
    await callback.message.edit_text(
        "<b>VPN Подписка</b>\n\n"
        "Выберите срок подписки:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="1 месяц - 150 руб", callback_data="period_1")],
            [types.InlineKeyboardButton(text="3 месяца - 400 руб", callback_data="period_3")],
            [types.InlineKeyboardButton(text="6 месяцев - 700 руб", callback_data="period_6")],
            [types.InlineKeyboardButton(text="Отмена", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data.startswith("period_"), PaymentStates.choosing_period)
async def on_period_selected(callback: types.CallbackQuery, state: FSMContext):
    period = int(callback.data.replace("period_", ""))
    prices = {1: 150, 3: 400, 6: 700}
    price = prices.get(period, 150)
    
    # Правильная грамматика для месяцев
    if period == 1:
        period_text = "1 месяц"
    elif period in [2, 3, 4]:
        period_text = f"{period} месяца"
    else:
        period_text = f"{period} месяцев"
    
    await state.update_data(period=period, price=price)
    await state.set_state(PaymentStates.waiting_for_screenshot)
    
    await callback.message.edit_text(
        f"<b>VPN Подписка</b>\n\n"
        f"Стоимость: {price} руб\n"
        f"Срок: {period_text}\n\n"
        f"Реквизиты платежа:\n"
        f"<code>{CARD_NUMBER}</code>\n\n"
        f"1. Оплатите по карте выше\n"
        f"2. Загрузите скриншот платежа\n"
        f"3. Нажмите кнопку ниже",
        parse_mode="HTML",
        reply_markup=buy_vpn_menu()
    )

@router.callback_query(F.data == "upload_payment")
async def on_upload_payment(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.waiting_for_screenshot)
    await callback.message.edit_text(
        "Загрузите скриншот или фото чека.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="buy_vpn")]
        ])
    )

@router.message(PaymentStates.waiting_for_screenshot, F.photo)
async def on_screenshot_received(message: types.Message, state: FSMContext):
    """Получить скриншот платежа для НОВОЙ подписки."""
    photo = message.photo[-1]
    await state.update_data(screenshot_file_id=photo.file_id)
    await state.set_state(PaymentStates.waiting_for_payment_confirmation)
    
    await message.answer(
        "✅ Скриншот получен!\n\nОтправляем на проверку?",
        reply_markup=payment_confirmation_menu()
    )

@router.message(PaymentStates.waiting_for_screenshot)
async def on_invalid_screenshot(message: types.Message):
    """Обработка неправильного формата при загрузке скриншота для новой подписки."""
    await message.answer(
        "❌ Пожалуйста, отправьте фото или скриншот (в формате изображения).",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="buy_vpn")]
        ])
    )

@router.callback_query(F.data == "confirm_payment", StateFilter(PaymentStates.waiting_for_payment_confirmation))
async def on_confirm_payment(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Подтверждение платежа для НОВОЙ подписки."""
    logger.info("🆕 on_confirm_payment вызван для НОВОЙ подписки")
    data = await state.get_data()
    screenshot_file_id = data.get("screenshot_file_id")
    period = data.get("period", 1)
    
    if not screenshot_file_id:
        await callback.answer("❌ Ошибка: скриншот не найден", show_alert=True)
        await state.clear()
        return
    
    await callback.message.edit_text("⏳ Отправляю заявку на проверку...")
    
    # ⚠️ ВАЖНО: Не перезаписываем uuid и email, только меняем статус на pending_payment
    # Если пользователь уже существует, его старые данные должны сохраниться
    user = await db.get_user(callback.from_user.id)
    
    if user:
        # Пользователь уже существует - просто обновляем статус
        await db.upsert_user(
            tg_id=callback.from_user.id,
            username=callback.from_user.username,
            uuid=user.get("uuid", ""),
            email=user.get("email", ""),
            status="pending_payment"
        )
    else:
        # Новый пользователь - будет заполнено после одобрения админом
        await db.upsert_user(
            tg_id=callback.from_user.id,
            username=callback.from_user.username,
            uuid="", 
            email="",
            status="pending_payment"
        )
    
    # Создаем заявку для НОВОЙ подписки (request_type="new")
    logger.info(f"📝 Создаю платеж для НОВОЙ подписки: period={period}, request_type='new'")
    payment_id = await db.create_payment_request(
        callback.from_user.id, 
        screenshot_file_id, 
        period=period,
        request_type="new"  # ← явно указываем что это новая подписка
    )
    
    # Уведомляем админа о заявке
    await notify_admin_about_payment(
        callback.bot, 
        payment_id, 
        callback.from_user.id, 
        callback.from_user.username
    )
    
    # Выводим подтверждение пользователю
    period_text = "1 месяц" if period == 1 else (f"{period} месяца" if period in [2, 3, 4] else f"{period} месяцев")
    await callback.message.edit_text(
        f"✅ <b>Заявка на оплату создана!</b>\n\n"
        f"ID: <code>{payment_id}</code>\n"
        f"Период: {period_text}\n\n"
        f"Ожидайте проверки администратора.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
        ])
    )
    
    # Очищаем состояние FSM
    await state.clear()


# ── ПРОДЛЕНИЕ ПОДПИСКИ ──────────────────────────────────────────────────
@router.callback_query(F.data == "renew_vpn")
async def on_renew_vpn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(PaymentStates.renewal_choosing_period)
    await callback.message.edit_text(
        "<b>Продление VPN Подписки</b>\n\n"
        "Выберите срок продления:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="1 месяц - 150 руб", callback_data="renewal_period_1")],
            [types.InlineKeyboardButton(text="3 месяца - 400 руб", callback_data="renewal_period_3")],
            [types.InlineKeyboardButton(text="6 месяцев - 700 руб", callback_data="renewal_period_6")],
            [types.InlineKeyboardButton(text="Отмена", callback_data="profile")]
        ])
    )

@router.callback_query(F.data.startswith("renewal_period_"), PaymentStates.renewal_choosing_period)
async def on_renewal_period_selected(callback: types.CallbackQuery, state: FSMContext):
    period = int(callback.data.replace("renewal_period_", ""))
    prices = {1: 150, 3: 400, 6: 700}
    price = prices.get(period, 150)
    
    # Правильная грамматика для месяцев
    if period == 1:
        period_text = "1 месяц"
    elif period in [2, 3, 4]:
        period_text = f"{period} месяца"
    else:
        period_text = f"{period} месяцев"
    
    await state.update_data(renewal_period=period, renewal_price=price)
    await state.set_state(PaymentStates.renewal_waiting_for_screenshot)
    
    await callback.message.edit_text(
        f"<b>Продление VPN Подписки</b>\n\n"
        f"Стоимость: {price} руб\n"
        f"Срок: {period_text}\n\n"
        f"Реквизиты платежа:\n"
        f"<code>{CARD_NUMBER}</code>\n\n"
        f"1. Оплатите по карте выше\n"
        f"2. Загрузите скриншот платежа\n"
        f"3. Нажмите кнопку ниже",
        parse_mode="HTML",
        reply_markup=buy_vpn_menu()
    )

@router.message(PaymentStates.renewal_waiting_for_screenshot, F.photo)
async def on_renewal_screenshot_received(message: types.Message, state: FSMContext):
    """Получить скриншот платежа для ПРОДЛЕНИЯ подписки."""
    photo = message.photo[-1]
    await state.update_data(renewal_screenshot_file_id=photo.file_id)
    await state.set_state(PaymentStates.renewal_waiting_for_payment_confirmation)
    
    await message.answer(
        "✅ Скриншот получен!\n\nОтправляем на проверку?",
        reply_markup=payment_confirmation_menu()
    )

@router.message(PaymentStates.renewal_waiting_for_screenshot)
async def on_invalid_renewal_screenshot(message: types.Message):
    """Обработка неправильного формата при загрузке скриншота для продления."""
    await message.answer(
        "❌ Пожалуйста, отправьте фото или скриншот (в формате изображения).",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="profile")]
        ])
    )

@router.callback_query(F.data == "confirm_payment", StateFilter(PaymentStates.renewal_waiting_for_payment_confirmation))
async def on_renewal_confirm_payment(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Подтверждение платежа для ПРОДЛЕНИЯ подписки."""
    logger.info("🔄 on_renewal_confirm_payment вызван для ПРОДЛЕНИЯ подписки")
    data = await state.get_data()
    screenshot_file_id = data.get("renewal_screenshot_file_id")
    period = data.get("renewal_period", 1)
    
    if not screenshot_file_id:
        await callback.answer("❌ Ошибка: скриншот не найден", show_alert=True)
        await state.clear()
        return
    
    # Проверяем, есть ли пользователь в БД (не может продлевать если не активный)
    user = await db.get_user(callback.from_user.id)
    if not user or not user.get("uuid") or not user.get("email"):
        await callback.message.edit_text(
            "❌ <b>Ошибка:</b> Вы не можете продлить подписку, которой нет.\n\n"
            "Сначала купите VPN.",
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Купить VPN", callback_data="buy_vpn")],
                [types.InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
            ])
        )
        await state.clear()
        return
    
    await callback.message.edit_text("⏳ Отправляю заявку на продление...")
    
    # Создаем заявку для ПРОДЛЕНИЯ подписки (request_type="renewal")
    logger.info(f"📝 Создаю платеж для ПРОДЛЕНИЯ подписки: period={period}, request_type='renewal'")
    payment_id = await db.create_payment_request(
        callback.from_user.id, 
        screenshot_file_id, 
        period=period,
        request_type="renewal"  # ← явно указываем что это продление
    )
    
    # Уведомляем админа о заявке на продление
    await notify_admin_about_payment(
        callback.bot, 
        payment_id, 
        callback.from_user.id, 
        callback.from_user.username
    )
    
    # Выводим подтверждение пользователю
    period_text = "1 месяц" if period == 1 else (f"{period} месяца" if period in [2, 3, 4] else f"{period} месяцев")
    await callback.message.edit_text(
        f"✅ <b>Заявка на продление создана!</b>\n\n"
        f"ID: <code>{payment_id}</code>\n"
        f"Период: {period_text}\n\n"
        f"Ожидайте проверки администратора.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="В мой кабинет", callback_data="profile")],
            [types.InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
        ])
    )
    
    # Очищаем состояние FSM
    await state.clear()