"""Bounded wait on the monthly-usage reservation lock (no database needed)."""
import types
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.services import usage_service


class _PgError(Exception):
    def __init__(self, sqlstate):
        super().__init__("lock timeout")
        self.sqlstate = sqlstate


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value


class _FakeDb:
    """Scripted session: records statements, raises on the reservation call."""

    def __init__(self, fail_with=None, reserve_value=1):
        self.fail_with, self.reserve_value = fail_with, reserve_value
        self.sql, self.rolled_back = [], False

    async def execute(self, statement, params=None):
        text = str(statement)
        self.sql.append(text)
        if "current_setting('lock_timeout')" in text:
            return _Result("0")
        if "try_increment_usage" in text and self.fail_with is not None:
            raise self.fail_with
        if "try_increment_usage" in text:
            return _Result(self.reserve_value)
        return _Result(None)

    async def rollback(self):
        self.rolled_back = True


@pytest.fixture
def wired(monkeypatch):
    async def limits(db, tenant_id):
        return "pro", [{"key": "invitations_per_month", "value": 100}]

    async def billing(db, tenant_id):
        return tenant_id

    monkeypatch.setattr(usage_service, "get_tenant_plan_limits", limits)
    monkeypatch.setattr("app.services.entitlement_service.resolve_billing_tenant", billing)


@pytest.mark.unit
@pytest.mark.parametrize("make", [
    lambda: _PgError("55P03"),
    lambda: types.SimpleNamespace(),  # filled below
])
def test_lock_timeout_detection(make):
    inner = make()
    exc = DBAPIError("SELECT 1", {}, inner if isinstance(inner, Exception) else Exception("x"))
    assert usage_service._is_lock_timeout(exc) is isinstance(inner, _PgError)


@pytest.mark.unit
def test_lock_timeout_detected_through_cause_and_class_name():
    class LockNotAvailableError(Exception):
        pass

    wrapped = Exception("adapter")
    wrapped.__cause__ = LockNotAvailableError("x")
    assert usage_service._is_lock_timeout(DBAPIError("s", {}, wrapped))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_waiter_is_answered_with_usage_busy_not_a_500(wired):
    db = _FakeDb(fail_with=DBAPIError("SELECT", {}, _PgError("55P03")))
    with pytest.raises(Exception) as caught:
        await usage_service.check_and_increment(db, uuid4(), "invitations_per_month", 5)
    err = caught.value
    assert err.status_code == 409
    assert err.detail["code"] == "USAGE_BUSY" and err.detail["limit_key"] == "invitations_per_month"
    assert err.headers["Retry-After"] == "5"
    assert db.rolled_back is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_other_database_errors_are_not_disguised_as_busy(wired):
    boom = DBAPIError("SELECT", {}, _PgError("40001"))
    db = _FakeDb(fail_with=boom)
    with pytest.raises(DBAPIError):
        await usage_service.check_and_increment(db, uuid4(), "invitations_per_month", 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_is_bounded_for_the_reservation_and_restored_afterwards(wired):
    db = _FakeDb(reserve_value=7)
    assert await usage_service.check_and_increment(db, uuid4(), "invitations_per_month", 1) == 7
    set_calls = [s for s in db.sql if "set_config('lock_timeout'" in s]
    assert len(set_calls) == 2, "must set the bound before and restore it after"
