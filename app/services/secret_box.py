"""
Symmetric encryption for short-lived secrets at rest (e.g. a pending org-request
applicant's password, which must be recoverable once — at approval — to create
the Supabase user, then wiped).

The encryption key is deliberately separate from the Supabase JWT verification
secret so that rotating either concern does not weaken the other.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet_from_secret(secret: str) -> Fernet:
    """Derive a Fernet instance from an application-managed secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _fernet() -> Fernet:
    settings = get_settings()
    secret = settings.org_request_encryption_key
    if not secret:
        if settings.is_production:
            raise RuntimeError("ORG_REQUEST_ENCRYPTION_KEY is required in production")
        secret = "dev-only-org-request-encryption-key-change-me"
    return _fernet_from_secret(secret)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a string; returns urlsafe ciphertext token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a token, accepting the former key only for pending legacy rows."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as primary_error:
        legacy_secret = get_settings().supabase_jwt_secret
        if legacy_secret:
            try:
                return _fernet_from_secret(legacy_secret).decrypt(token.encode("utf-8")).decode("utf-8")
            except (InvalidToken, ValueError):
                pass
        raise ValueError("failed to decrypt secret") from primary_error
