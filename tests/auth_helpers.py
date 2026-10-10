"""Shared helpers that let integration tests act as a real authenticated user.

The tenant middleware verifies bearer tokens and reads tenant memberships from
the database itself.  These helpers make tests exercise that same path:

* ``make_access_token`` signs a Supabase-shaped HS256 token with the configured
  test secret, so the middleware verifies it exactly as in production.
* ``BorrowedSession`` lets the middleware read and write through the test
  transaction, so rows seeded by fixtures are visible to tenant resolution.
* ``actor_client`` combines both into an HTTP client acting as one user.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.config import get_settings
from app.database import get_db, get_privileged_db
from app.main import app


class BorrowedSession:
    """Stands in for ``AsyncSessionLocal()``.

    Without this, rows seeded inside a test transaction are invisible to tenant
    resolution and every tenant-scoped request fails with 400.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


def make_access_token(user_id) -> str:
    """Sign an HS256 access token with the configured test secret."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "iss": settings.resolved_jwt_issuer,
        "email": "test-actor@example.com",
        "aal": "aal1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return pyjwt.encode(claims, settings.supabase_jwt_secret, algorithm="HS256")


def _current_user_for(user_id) -> CurrentUser:
    return CurrentUser(id=user_id, email="test-actor@example.com", role="authenticated")


@asynccontextmanager
async def actor_client(db_session: AsyncSession, user_id) -> AsyncIterator[AsyncClient]:
    """HTTP client acting as ``user_id``.

    Routes receive the transactional session.  The middleware receives it too and
    verifies the bearer token against the user's memberships.  Tenant headers are
    supplied per request by the caller, so a test can deliberately send another
    tenant's id.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_privileged_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: _current_user_for(user_id)
    headers = {"Authorization": f"Bearer {make_access_token(user_id)}"}
    with patch("app.middleware.AsyncSessionLocal", lambda: BorrowedSession(db_session)):
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
