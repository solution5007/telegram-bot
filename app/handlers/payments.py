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
    
    await state.update_data(period=period, price=price)
    await state.set_state(PaymentStates.waiting_for_screenshot)
    
    await callback.message.edit_text(
        f"<b>VPN Подписка</b>\n\n"
        f"Стоимость: {price} руб\n"
        f"Срок: {period} месяц{'а' if period == 1 else ('а' if period < 5 else 'ев')}\n\n"
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
    photo = message.photo[-1]
    await state.update_data(screenshot_file_id=photo.file_id)
    await state.set_state(PaymentStates.waiting_for_payment_confirmation)
    
    await message.answer(
        "Скриншот получен! Отправляем на проверку?",
        reply_markup=payment_confirmation_menu()
    )

@router.callback_query(F.data == "confirm_payment", StateFilter(PaymentStates.waiting_for_payment_confirmation))
async def on_confirm_payment(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    screenshot_file_id = data.get("screenshot_file_id")
    period = data.get("period", 1)
    
    await callback.message.edit_text("Отправляю заявку на проверку...")
    
    # Сохраняем/обновляем статус пользователя
    await db.upsert_user(
        tg_id=callback.from_user.id,
        username=callback.from_user.username,
        uuid="", 
        email="",
        status="pending_payment"
    )
    
    # Создаем заявку в БД (ВЫЗЫВАЕМ ОДИН РАЗ)
    payment_id = await db.create_payment_request(callback.from_user.id, screenshot_file_id, period)
    
    # Уведомляем админа (ВЫЗЫВАЕМ ОДИН РАЗ)
    await notify_admin_about_payment(callback.bot, payment_id, callback.from_user.id, callback.from_user.username)
    
    # Выводим подтверждение пользователю
    await callback.message.edit_text(
        f"✅ Заявка создана!\nID заявки: <code>{payment_id}</code>\n\nОжидайте проверки администратора.",
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
    
    await state.update_data(renewal_period=period, renewal_price=price)
    await state.set_state(PaymentStates.renewal_waiting_for_screenshot)
    
    await callback.message.edit_text(
        f"<b>Продление VPN Подписки</b>\n\n"
        f"Стоимость: {price} руб\n"
        f"Срок: {period} месяц{'а' if period == 1 else ('а' if period < 5 else 'ев')}\n\n"
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
    photo = message.photo[-1]
    await state.update_data(renewal_screenshot_file_id=photo.file_id)
    await state.set_state(PaymentStates.renewal_waiting_for_payment_confirmation)
    
    await message.answer(
        "Скриншот получен! Отправляем на проверку?",
        reply_markup=payment_confirmation_menu()
    )

@router.callback_query(F.data == "confirm_payment", StateFilter(PaymentStates.renewal_waiting_for_payment_confirmation))
async def on_renewal_confirm_payment(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    
    # Проверяем, это продление или новая подписка
    if "renewal_screenshot_file_id" in data:
        screenshot_file_id = data.get("renewal_screenshot_file_id")
        period = data.get("renewal_period", 1)
        request_type = "renewal"
    else:
        screenshot_file_id = data.get("screenshot_file_id")
        period = data.get("period", 1)
        request_type = "new"
    
    await callback.message.edit_text("Отправляю заявку на проверку...")
    
    # Создаем заявку в БД
    payment_id = await db.create_payment_request(callback.from_user.id, screenshot_file_id, period, request_type)
    
    # Уведомляем админа
    await notify_admin_about_payment(callback.bot, payment_id, callback.from_user.id, callback.from_user.username)
    
    # Выводим подтверждение пользователю
    await callback.message.edit_text(
        f"✅ Заявка создана!\nID заявки: <code>{payment_id}</code>\n\nОжидайте проверки администратора.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="В главное меню", callback_data="main_menu")]
        ])
    )
    
    # Очищаем состояние FSM
    await state.clear()