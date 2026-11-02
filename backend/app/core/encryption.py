from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionError(RuntimeError):
    """Raised when encrypted token material cannot safely be accessed."""


class TokenCipher:
    """Fernet token encryption; keys are supplied by deployment configuration."""

    def __init__(self, key: str | None) -> None:
        if not key:
            self._fernet = None
        else:
            try:
                self._fernet = Fernet(key.encode("ascii"))
            except (ValueError, TypeError) as exc:
                raise TokenEncryptionError("ENCRYPTION_KEY must be a valid Fernet key") from exc

    def encrypt(self, token: str) -> bytes:
        if self._fernet is None:
            raise TokenEncryptionError("ENCRYPTION_KEY is required before storing OAuth tokens")
        return self._fernet.encrypt(token.encode("utf-8"))

    def decrypt(self, token_ciphertext: bytes) -> str:
        if self._fernet is None:
            raise TokenEncryptionError("ENCRYPTION_KEY is required before reading OAuth tokens")
        try:
            return self._fernet.decrypt(token_ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise TokenEncryptionError("OAuth token ciphertext could not be decrypted") from exc
