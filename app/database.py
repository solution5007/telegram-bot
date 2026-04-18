#database.py
"""Хранилище пользователей в JSON-файле (без внешних зависимостей)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

# Структура файла:
# {
#   "users": {
#       "123456789": {
#           "tg_id": 123456789,
#           "username": "john",
#           "uuid": "550e8400-...",
#           "email": "john_123456789",
#           "status": "active",  # active, pending_payment
#           "plan": "standard",  # стандартный план
#           "expiry_time": "2024-01-01T12:00:00"  # дата окончания подписки
#       },
#       ...
#   },
#   "payments": {
#       "payment_id": {
#           "tg_id": 123456789,
#           "type": "new",  # new, renewal
#           "status": "pending",  # pending, approved, rejected
#           "created_at": "2024-01-01T12:00:00",
#           "screenshot_file_id": "AgAC...",
#           "admin_note": "test note",
#           "period": 1  # 1, 3 или 6 месяцев
#       },
#       ...
#   }
# }


def _path() -> Path:
    return Path(settings.db_path)


def _load() -> dict:
    """Читает JSON-файл. Если файла нет — возвращает структуру по умолчанию."""
    p = _path()
    if not p.exists():
        return {"users": {}, "payments": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # Миграция из старого формата
        if data and not isinstance(list(data.values())[0], dict) or "users" not in data:
            # Старый формат: {tg_id: {...}}
            old_data = data
            data = {"users": old_data, "payments": {}}
            _save(data)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Ошибка чтения базы данных: %s", exc)
        return {"users": {}, "payments": {}}


def _save(data: dict) -> None:
    """Записывает dict в JSON-файл с отступами (читабельный вид)."""
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Ошибка сохранения базы данных: %s", exc)


async def init_db() -> None:
    """Создаёт файл БД с правильной структурой, если его ещё нет."""
    if not _path().exists():
        _save({"users": {}, "payments": {}}) # Важна структура!
    logger.info("База данных инициализирована: %s", _path().resolve())


async def close_db() -> None:
    """Ничего закрывать не нужно — файловое хранилище."""
    logger.info("База данных закрыта.")


# ── CRUD ────────────────────────────────────────────────────────────────
async def get_user(tg_id: int) -> Optional[dict]:
    """Возвращает dict с данными пользователя или None."""
    data = _load()
    return data["users"].get(str(tg_id))


async def upsert_user(tg_id: int, username: str | None, uuid: str, email: str, status: str = "pending_payment", expiry_time: str | int | None = None) -> None:
    """Создаёт или обновляет запись о пользователе."""
    data = _load()
    user_data = {
        "tg_id": tg_id,
        "username": username,
        "uuid": uuid,
        "email": email,
        "status": status,
        "plan": "standard",
    }
    if expiry_time is not None:
        user_data["expiry_time"] = expiry_time
    data["users"][str(tg_id)] = user_data
    _save(data)
    logger.info("Пользователь %s сохранён.", tg_id)


async def get_all_users() -> list[dict]:
    """Возвращает список всех пользователей."""
    data = _load()
    return list(data["users"].values())


# ── ПЛАТЕЖИ ──────────────────────────────────────────────────────────────
async def create_payment_request(tg_id: int, screenshot_file_id: str, period: int = 1, request_type: str = "new") -> str:
    """Создаёт заявку на платёж. Возвращает ID заявки.
    
    Args:
        tg_id: ID пользователя в Telegram
        screenshot_file_id: file_id скриншота платежа
        period: количество месяцев (1, 3 или 6)
        request_type: тип заявки ("new" или "renewal")
    """
    import uuid as uuid_lib
    payment_id = str(uuid_lib.uuid4())
    data = _load()
    
    data["payments"][payment_id] = {
        "tg_id": tg_id,
        "type": request_type,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "screenshot_file_id": screenshot_file_id,
        "admin_note": "",
        "period": period,
    }
    _save(data)
    logger.info("Заявка на %s (%s месяцев) %s создана для пользователя %s", 
                "новую подписку" if request_type == "new" else "продление", 
                period, payment_id, tg_id)
    return payment_id


async def get_payment_request(payment_id: str) -> Optional[dict]:
    """Получить заявку на платёж."""
    data = _load()
    return data["payments"].get(payment_id)


async def get_pending_payments() -> list[tuple[str, dict]]:
    """Получить все заявки со статусом 'pending'. Возвращает список (payment_id, data)."""
    data = _load()
    return [(pid, p) for pid, p in data["payments"].items() if p["status"] == "pending"]


async def approve_payment(payment_id: str, admin_note: str = "") -> bool:
    """Одобрить платёж. Возвращает True если успешно."""
    data = _load()
    if payment_id not in data["payments"]:
        return False
    
    payment = data["payments"][payment_id]
    payment["status"] = "approved"
    payment["admin_note"] = admin_note
    
    # Обновляем статус пользователя на active
    tg_id = str(payment["tg_id"])
    if tg_id in data["users"]:
        data["users"][tg_id]["status"] = "active"
    
    _save(data)
    logger.info("Платёж %s одобрен", payment_id)
    return True


async def reject_payment(payment_id: str, admin_note: str = "") -> bool:
    """Отклонить платёж. Возвращает True если успешно."""
    data = _load()
    if payment_id not in data["payments"]:
        return False
    
    payment = data["payments"][payment_id]
    payment["status"] = "rejected"
    payment["admin_note"] = admin_note
    _save(data)
    logger.info("Платёж %s отклонён", payment_id)
    return True
    
async def delete_payment_request(payment_id: str) -> bool:
    """Полностью удаляет заявку на оплату из списка."""
    data = _load() # Загружаем данные через твою функцию
    
    if payment_id in data.get("payments", {}):
        # Удаляем заявку
        payment = data["payments"].pop(payment_id)
        tg_id = str(payment.get("tg_id"))

        # Если пользователь был в статусе "ожидания", удаляем и его, 
        # чтобы он мог подать заявку заново с чистого листа
        if tg_id in data["users"] and data["users"][tg_id]["status"] == "pending_payment":
            del data["users"][tg_id]
            logger.info("Пользователь %s удален вместе с отклоненной заявкой.", tg_id)

        _save(data) # Сохраняем файл через твою функцию
        logger.info("Заявка %s полностью удалена из БД.", payment_id)
        return True
    
    return False

async def get_user_payment_status(tg_id: int) -> Optional[dict]:
    """Получить последнюю заявку пользователя."""
    data = _load()
    user_payments = [p for p in data["payments"].values() if p["tg_id"] == tg_id]
    if user_payments:
        return sorted(user_payments, key=lambda x: x["created_at"], reverse=True)[0]
    return None
