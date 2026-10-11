"""Read-only mode after a paid plan ends: what is still allowed, phone validation."""
import pytest

from app.routes.subscriptions import SubscriptionRequestBody, CustomPlanRequestSubmit
from app.services.subscription_state import write_allowed_when_expired


@pytest.mark.unit
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_reads_are_always_allowed(method):
    assert write_allowed_when_expired(method, "/api/v1/events/123")


@pytest.mark.unit
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/events"),
    ("PATCH", "/api/v1/events/abc"),
    ("DELETE", "/api/v1/guests/abc"),
    ("POST", "/api/v1/fast-invitations/generate"),
    ("POST", "/api/v1/invitations/batch"),
    ("POST", "/api/v1/teams/1/members"),
    ("PUT", "/api/v1/roles/1/permissions"),
    ("POST", "/api/v1/mobile/checkins"),      # scanning is blocked unless explicitly enabled
])
def test_every_other_write_is_refused(method, path):
    assert write_allowed_when_expired(method, path) is False


@pytest.mark.unit
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/subscriptions/request"),
    ("POST", "/api/v1/custom-plans"),
    ("POST", "/api/v1/custom-plans/abc/request"),
    ("POST", "/api/v1/notifications/read-all"),
    ("PATCH", "/api/v1/profile"),
])
def test_renewal_and_account_writes_stay_available(method, path):
    assert write_allowed_when_expired(method, path) is True


@pytest.mark.unit
def test_scanning_can_be_kept_with_the_switch():
    assert write_allowed_when_expired("POST", "/api/v1/mobile/checkins/sync", allow_checkin=True)
    assert not write_allowed_when_expired("POST", "/api/v1/events", allow_checkin=True)


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("+967 777 123 456", "+967777123456"),
    ("00967777123456", "00967777123456"),
    ("0777-123-456", "0777123456"),
    ("(+20) 100 123 4567", None),   # parentheses around the + are not accepted
])
def test_phone_is_normalised(raw, expected):
    if expected is None:
        with pytest.raises(Exception):
            SubscriptionRequestBody(plan_code="pro", contact_phone=raw)
    else:
        assert SubscriptionRequestBody(plan_code="pro", contact_phone=raw).contact_phone == expected


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", "abc", "12", "+" , "777 12", "1" * 20])
def test_invalid_phone_numbers_are_rejected(bad):
    with pytest.raises(Exception):
        SubscriptionRequestBody(plan_code="pro", contact_phone=bad)
    with pytest.raises(Exception):
        CustomPlanRequestSubmit(contact_phone=bad)
