#config.py
"""Настройки приложения через pydantic‑settings (читает .env)."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Все настройки подтягиваются из переменных окружения / .env."""

    # --- Telegram ---
    bot_token: str
    admin_id: int

    # --- 3x-ui Panel ---
    panel_url: str
    panel_username: str
    panel_password: str
    panel_root_path: str = "/"
    panel_2fa_secret: str = ""

    # --- VLESS Reality ---
    vless_public_key: str
    vless_sni: str = "api.github.com"
    vless_sid: str = ""

    # --- Платежная система ---
    card_number: str = Field(default="5500 0000 0000 0000", description="Номер банковской карты для платежей")
    payment_amount: str = Field(default="150", description="Сумма платежа в рублях")

    # --- Пути ---
    # Локально: создаётся users.json рядом с кодом.
    # В Docker: переопределяется через .env → DB_PATH=/data/users.json
    db_path: str = Field(default="users.json", description="Путь к JSON-файлу с пользователями")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()  # type: ignore[call-arg]
