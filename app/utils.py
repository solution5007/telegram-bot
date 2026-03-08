"""Генерация VLESS‑ссылки и прочие утилиты."""

from app.config import settings


def generate_vless_link(uuid_str: str, email: str) -> str:
    """Формирует VLESS Reality ссылку для клиентского приложения."""
    server_ip = (
        settings.panel_url
        .replace("https://", "")
        .replace("http://", "")
        .split(":")[0]
    )
    return (
        f"vless://{uuid_str}@{server_ip}:443"
        f"?security=reality"
        f"&sni={settings.vless_sni}"
        f"&fp=chrome"
        f"&pbk={settings.vless_public_key}"
        f"&sid={settings.vless_sid}"
        f"&type=tcp"
        f"&flow=xtls-rprx-vision"
        f"&headerType=none"
        f"#{email}"
    )
