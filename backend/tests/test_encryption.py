import pytest
from cryptography.fernet import Fernet

from app.core.encryption import TokenCipher, TokenEncryptionError


def test_token_cipher_encrypts_and_decrypts() -> None:
    cipher = TokenCipher(Fernet.generate_key().decode("ascii"))
    ciphertext = cipher.encrypt("fake-test-token")
    assert ciphertext != b"fake-test-token"
    assert cipher.decrypt(ciphertext) == "fake-test-token"


def test_token_cipher_requires_configured_key() -> None:
    with pytest.raises(TokenEncryptionError):
        TokenCipher(None).encrypt("fake-test-token")
