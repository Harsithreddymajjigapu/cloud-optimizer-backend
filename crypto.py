import os

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")


def _cipher():
    """
    Build the cipher, failing loudly if the key is missing or malformed.

    This raises at call time rather than import time so the app still starts in
    environments that never touch cloud credentials (running the test suite,
    for example).
    """
    if not ENCRYPTION_KEY:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"ENCRYPTION_KEY is not a valid Fernet key: {exc}")


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns a string safe to put in a text column."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypt a stored secret.

    InvalidToken means the value was encrypted with a different key, or the
    column holds plaintext written before encryption was added.
    """
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise RuntimeError(
            "Stored credential could not be decrypted. It was encrypted with a "
            "different ENCRYPTION_KEY, or predates encryption. The account must "
            "be re-linked."
        )