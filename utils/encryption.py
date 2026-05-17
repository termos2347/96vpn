from cryptography.fernet import Fernet
from config import settings

fernet = Fernet(settings.ENCRYPTION_KEY.encode())

def encrypt_password(password: str) -> str:
    if not password:
        return ""
    return fernet.encrypt(password.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    if not encrypted:
        return ""
    return fernet.decrypt(encrypted.encode()).decode()