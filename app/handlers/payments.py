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
    waiting_for_screenshot = State()
    waiting_for_payment_confirmation = State()

@router.callback_query(F.data == "buy_vpn")
async def on_buy_vpn(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<b>VPN Подписка</b>\n\n"
        f"Стоимость: {PAYMENT_AMOUNT} руб\n"
        f"Срок: 1 месяц\n\n"
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
    payment_id = await db.create_payment_request(callback.from_user.id, screenshot_file_id)
    
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