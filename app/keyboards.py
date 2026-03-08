"""Клавиатуры (Inline) — вынесены в отдельный модуль."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(has_vpn: bool) -> InlineKeyboardMarkup:
    """Главное меню: кнопка зависит от наличия VPN."""
    builder = InlineKeyboardBuilder()
    if has_vpn:
        builder.row(InlineKeyboardButton(text="Мой кабинет", callback_data="profile"))
    else:
        builder.row(InlineKeyboardButton(text="Купить VPN", callback_data="buy_vpn"))
    return builder.as_markup()


def profile_menu() -> InlineKeyboardMarkup:
    """Меню личного кабинета."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Обновить", callback_data="profile"))
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def to_profile_menu() -> InlineKeyboardMarkup:
    """Одна кнопка «В кабинет»."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Мой кабинет", callback_data="profile"))
    return builder.as_markup()


def buy_vpn_menu() -> InlineKeyboardMarkup:
    """Меню покупки VPN."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Загрузить платёж", callback_data="upload_payment"))
    builder.row(InlineKeyboardButton(text="Отмена", callback_data="main_menu"))
    return builder.as_markup()


def payment_confirmation_menu() -> InlineKeyboardMarkup:
    """Меню подтверждения платежа."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Я оплатил", callback_data="confirm_payment"))
    builder.row(InlineKeyboardButton(text="Отмена", callback_data="main_menu"))
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    """Админ меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Заявки на оплату", callback_data="admin_payments"))
    builder.row(InlineKeyboardButton(text="Все пользователи", callback_data="admin_users"))
    builder.row(InlineKeyboardButton(text="Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def admin_payments_pagination(page: int, total: int) -> InlineKeyboardMarkup:
    """Меню для навигации по заявкам."""
    builder = InlineKeyboardBuilder()
    
    if page > 0:
        builder.row(InlineKeyboardButton(text="Назад", callback_data=f"admin_payments_{page - 1}"))
    if (page + 1) * 5 < total:
        builder.row(InlineKeyboardButton(text="Далее", callback_data=f"admin_payments_{page + 1}"))
    
    builder.row(InlineKeyboardButton(text="Назад в админ", callback_data="admin_menu"))
    return builder.as_markup()


def approve_reject_payment(payment_id: str) -> InlineKeyboardMarkup:
    """Меню для принятия/отклонения платежа."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Одобрить", callback_data=f"approve_payment_{payment_id}"),
        InlineKeyboardButton(text="Отклонить", callback_data=f"reject_payment_{payment_id}")
    )
    builder.row(InlineKeyboardButton(text="Назад", callback_data="admin_payments_0"))
    return builder.as_markup()
