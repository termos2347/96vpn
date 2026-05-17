import pytest
from utils.encryption import encrypt_password, decrypt_password, is_encrypted

def test_encryption():
    original = "my_secret_password"
    encrypted = encrypt_password(original)
    assert encrypted != original
    assert is_encrypted(encrypted)
    decrypted = decrypt_password(encrypted)
    assert decrypted == original

def test_empty():
    assert encrypt_password("") == ""
    assert decrypt_password("") == ""
    assert is_encrypted("") == False

def test_plain_text_auto_decrypt():
    plain = "not_encrypted"
    # При вызове decrypt_password с незашифрованной строкой вернёт её как есть
    assert decrypt_password(plain) == plain