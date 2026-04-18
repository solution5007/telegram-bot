#user.py
"""Хендлеры пользовательских команд и callback‑запросов."""

from aiogram import Router, types, F
from aiogram.filters import CommandStart
from datetime import datetime

from app import database as db
from app.keyboards import main_menu, profile_menu, to_profile_menu
from app.panel import PanelAPI
from app.utils.generate_vless import generate_vless_link

router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(message: types.Message, panel: PanelAPI) -> None:
    user = await db.get_user(message.from_user.id)

    # Проверяем статус: пользователь считается активным только если:
    # 1. Существует в БД
    # 2. status == "active"
    # 3. Имеет uuid и email
    has_active_vpn = (
        user
        and user.get("status") == "active"
        and user.get("uuid")
        and user.get("email")
    )

    if has_active_vpn:
        text = "С возвращением! Управление твоим VPN ниже"
    else:
        text = "Привет! Нажми кнопку ниже, чтобы купить VPN-подключение."

    await message.answer(text, reply_markup=main_menu(has_vpn=has_active_vpn))


@router.callback_query(F.data == "main_menu")
async def on_main_menu(callback: types.CallbackQuery) -> None:
    """Главное меню."""
    user = await db.get_user(callback.from_user.id)
    has_active_vpn = (
        user
        and user.get("status") == "active"
        and user.get("uuid")
        and user.get("email")
    )
    
    if has_active_vpn:
        text = "Главное меню\n\nВыберите действие:"
    else:
        text = "Главное меню\n\nУ вас еще нет активного VPN."
    
    await callback.message.edit_text(
        text,
        reply_markup=main_menu(has_vpn=has_active_vpn)
    )


@router.callback_query(F.data == "profile")
async def on_profile(callback: types.CallbackQuery, panel: PanelAPI) -> None:
    await callback.message.edit_text("Загружаю статистику...")

    user = await db.get_user(callback.from_user.id)
    
    # Проверяем, что пользователь существует и имеет все необходимые данные
    if not user or not user.get("uuid") or not user.get("email"):
        await callback.message.edit_text("❌ Данные профиля не найдены в базе.")
        return

    uuid_str = user["uuid"]
    email = user["email"]
    user_status = user.get("status", "inactive")  # Безопасный дефолт

    up, down = await panel.get_client_traffic(email)
    total_gb = round((up + down) / (1024**3), 2)

    link = generate_vless_link(uuid_str, email)
    
    status_text = "Активен" if user_status == "active" else "Ожидание подтверждения платежа"
    
    expiry_info = ""
    expiry_time = user.get("expiry_time")
    if expiry_time is not None:
        if expiry_time == 0:
            expiry_info = "Дата окончания: Безлимит ♾️\n"
        elif isinstance(expiry_time, str):
            try:
                expiry_dt = datetime.fromisoformat(expiry_time)
                expiry_info = f"Дата окончания: {expiry_dt.strftime('%d.%m.%Y')}\n"
            except:
                pass
    
    message_text = (
        f"Личный кабинет\n\n"
        f"Пользователь: {email}\n"
        f"Статус: {status_text}\n"
        f"{expiry_info}"
        f"Потрачено трафика: {total_gb} GB\n"
        f"План: Стандартный\n\n"
        f"Твой ключ подключения:\n\n"
        f"<code>{link}</code>\n\n"
        f"Используйте её в любом клиенте для создания подключения."
    )
    
    await callback.message.edit_text(
        message_text,
        parse_mode="HTML",
        reply_markup=profile_menu(),
    )

@router.callback_query(F.data == "show_instructions")
async def show_instructions(callback: types.CallbackQuery) -> None:
    """Показывает инструкцию пользователю."""
    instruction_text = """📖 <b>Инструкция по настройке VPN</b>

Для подключения используйте скопированный ключ (ссылку).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>1️⃣ Выбор приложения</b>

Установите подходящий клиент для вашего устройства:

<b>Android:</b> v2rayNG
<b>iOS (iPhone/iPad):</b> Streisand или V2Box
<b>Windows:</b> v2rayN

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<b>2️⃣ Настройка подключения</b>

<b>📱 Для Android (v2rayNG)</b>
1. Скопируйте ключ
2. Откройте приложение и нажмите <b>"+"</b> в верхнем меню
3. Выберите <b>"Импорт профиля из буфера обмена"</b>
4. Нажмите на профиль (слева появится полоса)
5. Нажмите круглую кнопку с логотипом V внизу

<b>📱 Для iOS (Streisand / V2Box)</b>
1. Скопируйте ключ
2. Откройте приложение
3. Нажмите кнопку <b>"+"</b> (или "Add Config")
4. Выберите <b>"Import from Clipboard"</b>
5. Перейдите на главную и включите тумблер <b>"Connected/On"</b>

<b>💻 Для Windows (v2rayN)</b>
1. Скопируйте ключ
2. Откройте v2rayN
3. Нажмите <b>"Серверы"</b> в верхнем меню
4. Выберите <b>"Импортировать сервер из буфера обмена"</b>
5. Выберите добавленный сервер и нажмите Enter
6. Включите системный прокси: правая кнопка мыши на иконку → <b>"Режим системного прокси"</b> → <b>"Global"</b>"""
    
    await callback.answer()
    await callback.message.edit_text(
        instruction_text,
        parse_mode="HTML",
        reply_markup=to_profile_menu()
    )