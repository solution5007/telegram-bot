#panel.py
"""Клиент для 3x‑ui панели (aiohttp + TOTP 2FA)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import uuid
from typing import Optional

import aiohttp
import pyotp

from app.config import settings

logger = logging.getLogger(__name__)


class PanelAPI:
    """Асинхронный клиент к REST API панели 3x‑ui."""

    def __init__(self) -> None:
        self._base_url: str = settings.panel_url.rstrip("/")
        self._root: str = settings.panel_root_path.strip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    # ── helpers ──────────────────────────────────────────────────────────
    def _url(self, endpoint: str) -> str:
        """Склейка URL с учётом кастомного root‑пути."""
        ep = endpoint.lstrip("/")
        if self._root:
            return f"{self._base_url}/{self._root}/{ep}"
        return f"{self._base_url}/{ep}"

    @staticmethod
    def _totp_code(offset: int = 0) -> Optional[str]:
        """Генерация TOTP‑кода с возможным сдвигом по 30‑секундному окну."""
        if not settings.panel_2fa_secret:
            return ""
        try:
            clean = re.sub(r"[^A-Z2-7]", "", settings.panel_2fa_secret.upper())
            totp = pyotp.TOTP(clean)
            target = datetime.datetime.now() + datetime.timedelta(seconds=offset * 30)
            return totp.at(target)
        except Exception as exc:
            logger.error("Ошибка генерации TOTP: %s", exc)
            return None

    async def _ensure_session(self) -> Optional[aiohttp.ClientSession]:
        """Возвращает авторизованную aiohttp‑сессию (создаёт при необходимости)."""
        if self._session and not self._session.closed:
            return self._session

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self._base_url}/{self._root}/panel/inbounds",
        }
        connector = aiohttp.TCPConnector(ssl=False)
        # unsafe=True — разрешает хранить куки от IP-адресов (не только от доменов).
        # Без этого aiohttp молча дропает Set-Cookie после логина, и все
        # следующие запросы идут без авторизации → 404.
        cookie_jar = aiohttp.CookieJar(unsafe=True)
        self._session = aiohttp.ClientSession(connector=connector, headers=headers, cookie_jar=cookie_jar)

        login_url = self._url("login")

        for offset in (0, -1, 1):
            code = self._totp_code(offset)
            if code is None:
                continue

            payload = {
                "username": settings.panel_username,
                "password": settings.panel_password,
                "loginSecret": code,
            }
            logger.info("Попытка логина в панель (TOTP offset=%s)", offset)
            try:
                async with self._session.post(login_url, data=payload) as resp:
                    text = await resp.text()
                    if resp.status == 200 and '"success":true' in text.lower():
                        logger.info("Успешный вход в панель!")
                        return self._session
            except Exception as exc:
                logger.error("Ошибка сети при логине: %s", exc)

        logger.error("Не удалось войти в панель ни с одним TOTP‑кодом.")
        return None

    # ── API‑методы ───────────────────────────────────────────────────────
    async def get_vless_inbound_id(self) -> Optional[int]:
        """Находит первый Inbound с протоколом VLESS и возвращает его ID."""
        session = await self._ensure_session()
        if not session:
            return None

        url = self._url("panel/api/inbounds/list")
        logger.info("Запрос инбаундов: %s", url)

        try:
            async with session.get(url, timeout = 5) as resp:
                if resp.status != 200:
                    logger.error("Сервер ответил %s", resp.status)
                    return None
                data = await resp.json(content_type=None)

            if not data.get("success"):
                logger.error("API ошибка: %s", data.get("msg"))
                return None

            for ib in data.get("obj", []):
                proto = ib.get("protocol", "").lower()
                remark = ib.get("remark", "").lower()
                logger.info("  id=%s  proto=%s  remark=%s", ib.get("id"), proto, ib.get("remark"))
                
                if proto == "vless" or "vless" in remark:
                    logger.info("Выбран VLESS inbound id=%s", ib.get("id"))
#                    await asyncio.sleep(1)
                    return ib["id"]

            logger.warning("VLESS inbound не найден — создай его в панели.")
        except Exception as exc:
            logger.error("Ошибка при запросе инбаундов: %s", exc)

        return None

    async def add_client(self, tg_id: int, username: str | None, expiry_time: int = 0) -> tuple[Optional[str], Optional[str]]:
        """Создаёт клиента в VLESS inbound. Возвращает ``(uuid, email)``."""
#        inbound_id = await self.get_vless_inbound_id()
#        if inbound_id is None:
#            return None, None
        
        inbound_id = 1

        session = await self._ensure_session()
        if not session:
            return None, None

        client_uuid = str(uuid.uuid4())
        email = f"{username}_{tg_id}" if username else f"user_{tg_id}"

        payload = {
            "id": inbound_id,
            "settings": json.dumps(
                {
                    "clients": [
                        {
                            "id": client_uuid,
                            "flow": "xtls-rprx-vision",
                            "email": email,
                            "limitIp": 0,
                            "totalGB": 0,
                            "expiryTime": expiry_time,
                            "enable": True,
                            "tgId": str(tg_id),
                            "subId": "",
                        }
                    ]
                }
            ),
        }

        url = self._url("panel/api/inbounds/addClient")
        logger.info("Создаю клиента %s (uuid=%s)...", email, client_uuid)

        try:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("success"):
                    logger.info("Клиент %s создан!", email)
#                    await asyncio.sleep(1)
                    return client_uuid, email
                
                # Проверяем ошибку Duplicate email - клиент уже существует
                error_msg = data.get("msg", "")
                if "Duplicate email" in error_msg:
                    logger.warning(f"Клиент с email {email} уже существует в панели, обновляю expiry_time")
                    # Клиент существует, просто обновляем его expiry time
                    if await self.update_client_expiry(email, expiry_time):
                        logger.info(f"Expiry time для существующего клиента {email} обновлен")
                        # Возвращаем специальный маркер что это существующий клиент
                        return "existing", email
                    else:
                        logger.error(f"Не удалось обновить expiry time для существующего клиента {email}")
                        return None, None
                
                logger.error("Ошибка addClient: %s", error_msg)
        except Exception as exc:
            logger.error("Ошибка API addClient: %s", exc)

        return None, None

    async def update_client_expiry(self, email: str, expiry_time: int) -> bool:
        """
        Обновляет expiryTime для клиента. expiry_time в миллисекундах.
        Отправляет полный объект inbound чтобы избежать validation errors.
        """
        inbound_id = 1  # предполагаем, что inbound_id = 1

        session = await self._ensure_session()
        if not session:
            logger.error("Не удалось создать сессию")
            return False

        # Получаем весь inbound
        get_url = self._url(f"panel/api/inbounds/get/{inbound_id}")
        try:
            async with session.get(get_url, timeout=5) as resp:
                data = await resp.json()
                if not data.get("success"):
                    logger.error("Ошибка получения inbound: %s", data.get("msg"))
                    return False
                
                inbound = data.get("obj")
                if not inbound:
                    logger.error("Inbound не найден")
                    return False
                
                # Находим клиента по email и обновляем его expiryTime
                settings_str = inbound.get("settings", "{}")
                if isinstance(settings_str, str):
                    try:
                        settings = json.loads(settings_str)
                    except json.JSONDecodeError as e:
                        logger.error("Ошибка парсинга settings: %s", e)
                        return False
                else:
                    settings = settings_str
                
                clients = settings.get("clients", [])
                client_found = False
                
                for client in clients:
                    if client.get("email") == email:
                        old_expiry = client.get("expiryTime")
                        client["expiryTime"] = expiry_time
                        client_found = True
                        logger.info(
                            "Найден клиент %s: старый expiry=%s, новый expiry=%s",
                            email, old_expiry, expiry_time
                        )
                        break
                
                if not client_found:
                    logger.warning("Клиент %s не найден в inbound %s", email, inbound_id)
                    return False
                
                # ⚠️ ВАЖНО: Отправляем полный inbound объект, не только settings
                # API требует все поля для валидации
                update_url = self._url(f"panel/api/inbounds/update/{inbound_id}")
                
                # Собираем обновленный payload с проверкой всех полей
                port = inbound.get("port")
                if port is None or port == 0:
                    logger.error("⚠️ Критическое: port inbound = %s, это может привести к ошибке", port)
                
                update_payload = {
                    "id": inbound.get("id"),
                    "enable": inbound.get("enable", True),
                    "port": port,
                    "protocol": inbound.get("protocol"),
                    "remark": inbound.get("remark", ""),
                    "settings": json.dumps(settings),
                    "streamSettings": inbound.get("streamSettings", "{}"),
                    "sniffing": inbound.get("sniffing", "{}"),
                    "allocate": inbound.get("allocate", "{}"),
                }
                
                logger.debug(
                    "Update payload для inbound %s: id=%s port=%s protocol=%s enable=%s",
                    inbound_id, update_payload.get("id"), port, 
                    update_payload.get("protocol"), update_payload.get("enable")
                )
                
                # Убираем None значения чтобы не сломать API, но НЕ убираем port
                update_payload = {k: v for k, v in update_payload.items() if v is not None}
                
                logger.debug("Отправляю update для inbound %s: %s", inbound_id, update_payload.keys())
                
                async with session.post(update_url, json=update_payload, timeout=5) as resp:
                    result = await resp.json()
                    if result.get("success"):
                        logger.info("✅ Expiry time для %s успешно обновлен на %s!", email, expiry_time)
                        return True
                    
                    logger.error("❌ Ошибка updateInbound: %s", result.get("msg"))
                    return False
        
        except asyncio.TimeoutError:
            logger.error("Timeout при обновлении expiry для %s", email)
            return False
        except Exception as exc:
            logger.error("Ошибка при обновлении expiry time для %s: %s", email, exc, exc_info=True)
            return False

    async def get_client_traffic(self, email: str) -> tuple[int, int]:
        """Возвращает ``(upload, download)`` в байтах."""
        session = await self._ensure_session()
        if not session:
            return 0, 0

        url = self._url(f"panel/api/inbounds/getClientTraffics/{email}")
        logger.info("Запрос трафика для %s…", email)

        try:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("success") and data.get("obj"):
#                    await asyncio.sleep(1)
                    return data["obj"].get("up", 0), data["obj"].get("down", 0)
        except Exception as exc:
            logger.error("Ошибка получения трафика: %s", exc)

        return 0, 0

    async def get_client_expiry(self, email: str) -> Optional[int]:
        """Возвращает expiryTime в миллисекундах или None."""
        session = await self._ensure_session()
        if not session:
            return None

        url = self._url(f"panel/api/inbounds/getClientTraffics/{email}")
        logger.info("Запрос expiry time для %s…", email)

        try:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("success") and data.get("obj"):
                    return data["obj"].get("expiryTime", 0)
        except Exception as exc:
            logger.error("Ошибка получения expiry time: %s", exc)

        return None

    async def get_inbounds(self) -> dict:
        """Возвращает список всех инбаундов."""
        session = await self._ensure_session()
        if not session:
            return {"success": False, "msg": "No session"}

        url = self._url("panel/api/inbounds/list")
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return {"success": False, "msg": f"Status {resp.status}"}
                return await resp.json(content_type=None)
        except Exception as exc:
            logger.error("Ошибка при запросе всех инбаундов: %s", exc)
            return {"success": False, "msg": str(exc)}
                
    # ── lifecycle ────────────────────────────────────────────────────────
    async def close(self) -> None:
        """Корректно закрывает HTTP‑сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("HTTP‑сессия панели закрыта.")
