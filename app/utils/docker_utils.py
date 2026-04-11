import logging

logger = logging.getLogger(__name__)

def get_docker_logs(container_name: str = "vpn-bot", lines: int = 20) -> str:
    # Т.к. бот внутри контейнера не видит команду 'docker', 
    # а логи нам нужны его собственные — проще вернуть заглушку 
    # или использовать библиотеку 'docker', но это сложно настраивать (нужен сокет).
    return "Функция логов через CLI недоступна внутри контейнера. Используйте 'docker logs vpn-bot' в консоли сервера."