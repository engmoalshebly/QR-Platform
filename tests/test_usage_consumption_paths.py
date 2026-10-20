from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.auth import CurrentUser
from app.routes import fast_invitations
from app.services import entitlement_service, feature_service, usage_service, fast_generation_service

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
@pytest.mark.parametrize('by_count', [False, True])
async def test_failed_fast_generation_rolls_back_without_commit(monkeypatch, by_count):
    tenant_id = uuid4()
    result = MagicMock()
    result.first.return_value = {"id": uuid4()}
    result.scalar.return_value = 0
    db = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(fast_invitations, 'get_tenant_id_from_header', lambda _: tenant_id)
    monkeypatch.setattr(fast_invitations, 'require_permission', AsyncMock())
    monkeypatch.setattr(fast_invitations, 'check_quota_mixed', AsyncMock())
    monkeypatch.setattr(feature_service, 'enforce_static_limit', AsyncMock())
    monthly = AsyncMock()
    monkeypatch.setattr(feature_service, 'enforce_monthly_limit', monthly)
    monkeypatch.setattr(fast_invitations, 'generate_invitations_fast', AsyncMock(return_value=SimpleNamespace(success=False, error_message='failed')))
    request = Request({'type': 'http', 'headers': []})
    user = CurrentUser(id=uuid4(), role='authenticated')
    with pytest.raises(HTTPException) as exc:
        if by_count:
            await fast_invitations.generate_invitations_by_count(
                fast_invitations.FastInvitationByCount(event_id=uuid4(), count=1), request, user, db)
        else:
            await fast_invitations.generate_invitations_fast_endpoint(
                fast_invitations.FastInvitationRequest(event_id=uuid4(), invitations=[{'guest_name': 'ضيف اختبار', 'guest_count': 4}]),
                request, BackgroundTasks(), user, db)
    assert exc.value.status_code == 400
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    assert monthly.await_args.kwargs['count'] == (1 if by_count else 4)


@pytest.mark.asyncio
async def test_fast_insert_never_commits_caller_transaction():
    response = MagicMock()
    response.mappings.return_value.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=response), commit=AsyncMock(), flush=AsyncMock())
    await fast_generation_service._create_invitations_batch(db, str(uuid4()), str(uuid4()), [{'guest_name': 'ضيف اختبار', 'guest_count': 3}])
    db.commit.assert_not_awaited()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('already_counted,allowed', [(1, True), (0, False)])
async def test_linked_member_consumes_no_second_seat(monkeypatch, already_counted, allowed):
    tenant_id, uid = uuid4(), uuid4()
    response = MagicMock()
    response.scalar.side_effect = [0, already_counted]  # pending invites, active candidate
    db = SimpleNamespace(execute=AsyncMock(return_value=response))
    monkeypatch.setattr(feature_service, 'acquire_plan_limit_lock', AsyncMock())
    monkeypatch.setattr(usage_service, 'get_seats_count', AsyncMock(return_value=1))
    monkeypatch.setattr(entitlement_service, 'get_billing_scope_tenant_ids', AsyncMock(return_value=[tenant_id]))
    monkeypatch.setattr(feature_service, 'get_plan_limit', AsyncMock(return_value=1))
    if allowed:
        await feature_service.check_seats_limit(db, tenant_id, adding_user_id=uid)
    else:
        with pytest.raises(HTTPException) as exc:
            await feature_service.check_seats_limit(db, tenant_id, adding_user_id=uid)
        assert exc.value.detail['requested'] == 1


@pytest.mark.asyncio
async def test_static_usage_failure_never_becomes_a_zero(monkeypatch):
    monkeypatch.setattr(entitlement_service, 'get_billing_scope_tenant_ids', AsyncMock(return_value=[uuid4()]))
    nested = MagicMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    db = SimpleNamespace(begin_nested=lambda: nested, execute=AsyncMock(side_effect=RuntimeError('database error')))
    with pytest.raises(HTTPException) as exc:
        await usage_service.get_static_usage(db, uuid4())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_public_registration_retry_returns_existing_without_consuming_quota(monkeypatch):
    from app.routes import registration_forms
    from app.models.registration_form import PublicRegistrationSubmit

    event_id, tenant_id, invitation_id = uuid4(), uuid4(), uuid4()
    rows = [
        {'id': event_id, 'tenant_id': tenant_id, 'logo_path': None},
        {'is_enabled': True, 'barcode_generation_mode': 'immediate',
         'success_message_ar': 'تم التسجيل', 'expires_at': None},
        None,  # advisory transaction lock
        {'id': invitation_id, 'token': 'existing-token', 'guest_name': 'ضيف',
         'ticket_class': 'normal', 'barcode_png_url': None, 'card_image_url': None},
    ]
    responses = []
    for row in rows:
        response = MagicMock()
        response.mappings.return_value.first.return_value = row
        responses.append(response)
    db = SimpleNamespace(execute=AsyncMock(side_effect=responses))
    quota = AsyncMock(side_effect=AssertionError('An idempotent retry must not check or consume quota'))
    monkeypatch.setattr(registration_forms, '_check_quota', quota)
    result = await registration_forms.public_register('test-event', PublicRegistrationSubmit(
        registration_request_id=uuid4(), guest_name='ضيف', guest_phone='+967777777777'), db)
    assert result['invitation']['id'] == str(invitation_id)
    quota.assert_not_awaited()
    assert db.execute.await_count == 4
