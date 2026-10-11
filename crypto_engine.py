import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class CryptoEngine:
    @staticmethod
    def derive_key(password: str, salt: bytes = b'stego_v6_salt') -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    @staticmethod
    def encrypt(data: bytes, password: str) -> bytes:
        if not password:
            return data
        return Fernet(CryptoEngine.derive_key(password)).encrypt(data)

    @staticmethod
    def decrypt(data: bytes, password: str) -> bytes:
        if not password:
            return data
        try:
            return Fernet(CryptoEngine.derive_key(password)).decrypt(data)
        except InvalidToken:
            raise ValueError("Decryption failed: Incorrect password or corrupted data.")