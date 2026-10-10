"""Authorization tests for platform-administrator lifecycle controls."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.auth import CurrentUser, get_current_user
from app.database import get_db, get_privileged_db
from app.main import app


async def _client_for(db_session, actor_id):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_privileged_db] = lambda: db_session

    async def current_user():
        return CurrentUser(id=actor_id, email="actor@example.com", role="authenticated")

    app.dependency_overrides[get_current_user] = current_user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_platform_staff_can_grant_and_revoke_an_existing_account(db_session):
    staff_id, target_id = uuid4(), uuid4()
    staff_email, target_email = f"staff-{staff_id}@example.com", f"target-{target_id}@example.com"
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:staff_id, :staff_email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000'),
               (:target_id, :target_email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
    """), {"staff_id": str(staff_id), "staff_email": staff_email, "target_id": str(target_id), "target_email": target_email})
    await db_session.execute(
        text("UPDATE profiles SET full_name = 'Platform Staff', is_staff = true WHERE id = :id"),
        {"id": str(staff_id)},
    )
    await db_session.execute(
        text("UPDATE profiles SET full_name = 'Target Account', is_staff = false WHERE id = :id"),
        {"id": str(target_id)},
    )

    client = await _client_for(db_session, staff_id)
    try:
        granted = await client.post("/api/v1/platform/staff", json={"email": target_email})
        assert granted.status_code == 201
        assert granted.json()["is_staff"] is True

        listed = await client.get("/api/v1/platform/staff")
        assert listed.status_code == 200
        # A deployment can already contain bootstrap platform staff; the
        # lifecycle contract is that both accounts created in this transaction
        # are present, not that they are the only two staff accounts globally.
        assert {str(staff_id), str(target_id)}.issubset({row["id"] for row in listed.json()})

        revoked = await client.delete(f"/api/v1/platform/staff/{target_id}")
        assert revoked.status_code == 204
        assert await db_session.scalar(text("SELECT is_staff FROM profiles WHERE id = :id"), {"id": str(target_id)}) is False

        self_revoke = await client.delete(f"/api/v1/platform/staff/{staff_id}")
        assert self_revoke.status_code == 400
    finally:
        await client.aclose()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_non_staff_cannot_promote_themselves(db_session):
    user_id = uuid4()
    email = f"user-{user_id}@example.com"
    await db_session.execute(text("""
        INSERT INTO auth.users (id, email, aud, role, email_confirmed_at, instance_id)
        VALUES (:id, :email, 'authenticated', 'authenticated', now(), '00000000-0000-0000-0000-000000000000')
    """), {"id": str(user_id), "email": email})
    await db_session.execute(text("UPDATE profiles SET full_name = 'Regular User', is_staff = false WHERE id = :id"), {"id": str(user_id)})

    client = await _client_for(db_session, user_id)
    try:
        response = await client.post("/api/v1/platform/staff", json={"email": email})
        assert response.status_code == 403
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
