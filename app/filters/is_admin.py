#is_admin.py
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from app.config import settings

class IsAdmin(BaseFilter):
    """Фильтр проверяет, является ли пользователь администратором."""
    
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        # event может быть и сообщением, и коллбэком (нажатием кнопки)
        return event.from_user.id == settings.admin_id