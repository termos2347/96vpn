from cryptography.fernet import Fernet, InvalidToken
from config import settings

fernet = Fernet(settings.ENCRYPTION_KEY.encode())

def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return fernet.encrypt(password.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        return fernet.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        # Если токен невалидный – возможно пароль ещё не зашифрован
        return encrypted

def is_encrypted(text: str) -> bool:
    """Проверяет, похожа ли строка на зашифрованную Fernet."""
    return text.startswith('gAAAAA') and len(text) > 20