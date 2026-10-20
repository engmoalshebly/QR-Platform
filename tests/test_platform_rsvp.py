import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from starlette.requests import Request
from app.routes import platform
from app.services import feature_service

pytestmark = pytest.mark.unit

@pytest.mark.parametrize('linked', [False, True])
def test_toggle_targets_selected_workspace_group_and_audits(monkeypatch, linked):
    primary, secondary, actor = uuid4(), uuid4(), uuid4()
    secondary = secondary if linked else primary
    monkeypatch.setattr(platform, '_resolve_workspace_scope', AsyncMock(return_value=(str(primary),str(secondary),linked)))
    audit = AsyncMock()
    monkeypatch.setattr(platform, 'log_audit', audit)
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    result = asyncio.run(platform.update_platform_rsvp(primary, platform.PlatformRsvpUpdate(enabled=True), Request({'type':'http','headers':[],'client':('127.0.0.1',1)}), SimpleNamespace(id=actor), db))
    assert result['enabled'] is True
    assert db.execute.await_count == (2 if linked else 1)
    assert audit.await_count == db.execute.await_count
    assert {call.args[1]['tid'] for call in db.execute.await_args_list} == {str(primary),str(secondary)}
    db.commit.assert_awaited_once()

def test_mixed_group_is_reported(monkeypatch):
    primary, secondary = uuid4(), uuid4()
    monkeypatch.setattr(platform, '_resolve_workspace_scope', AsyncMock(return_value=(str(primary),str(secondary),True)))
    monkeypatch.setattr(feature_service, 'check_feature_flag', AsyncMock(side_effect=[True,False]))
    result = asyncio.run(platform.get_platform_rsvp(primary, SimpleNamespace(id=uuid4()), object()))
    assert result == {'enabled':False, 'mixed':True}
