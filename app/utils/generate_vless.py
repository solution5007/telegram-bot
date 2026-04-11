#generate_vless.py
from app.config import settings

def generate_vless_link(uuid_str: str, email: str) -> str:
    """Формирует VLESS Reality ссылку для клиентского приложения."""
    server_ip = (
        settings.panel_url
        .replace("https://", "")
        .replace("http://", "")
        .split(":")[0]
    )
    
    # Формируем параметры. 
    # ВАЖНО: Убедись, что settings.vless_sid НЕ ПУСТОЙ в .env
    params = (
        f"type=tcp"
        f"&encryption=none" # Добавили для надежности, как в рабочей ссылке
        f"&security=reality"
        f"&pbk={settings.vless_public_key}"
        f"&fp=random"
        f"&sni={settings.vless_sni}"
        f"&sid={settings.vless_sid}"
        f"&spx=%2F"
        f"&flow=xtls-rprx-vision"
    )
    
    return f"vless://{uuid_str}@{server_ip}:443?{params}#%F0%9F%87%BA%F0%9F%87%B8%20reality-{email}"