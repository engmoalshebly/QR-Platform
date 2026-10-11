"""Authorization invariant: every state-changing route must be guarded.

ADR-0001 makes the application layer the only tenant-isolation boundary, so a
new mutating endpoint without a permission check is a cross-tenant leak.  This
test walks every route module and fails when a non-GET handler shows no guard,
directly or through a helper defined in the same module.

Routes that are public by design, or that are retired (410/403 stubs), are
listed in ALLOWED_UNGUARDED with the reason.  Adding to that list is a security
review decision, not a convenience.
"""
import ast
from pathlib import Path

import pytest

ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "routes"

# Names of functions that establish who the caller is allowed to act as.
# Entitlement helpers (require_feature / require_limit) are deliberately absent:
# they cap usage, they do not authorize the caller.
GUARD_TOKENS = (
    "require_permission", "require_any_permission", "require_staff",
    "require_platform_superadmin", "verify_membership", "has_permission",
    "require_owner", "require_admin", "require_event_access",
    "require_provider_event_access", "check_event_access",
    "check_provider_event_access", "require_team_lead", "_require_tenant_manager",
    "_require_role_admin", "_require_member_change_authority",
    "_require_assignable_field_role", "_require_field_session",
    "_task_access", "_manager_shift", "_supervisor_or_manager",
    "_is_shift_supervisor", "get_shift_with_provider_access",
    "require_active_gate_session", "_transition_booking", "TenantQuery",
)

MUTATING = {"post", "put", "patch", "delete"}

# (module file, function name) -> why no guard is expected.
ALLOWED_UNGUARDED: dict[tuple[str, str], str] = {
    ("mfa.py", "mfa_enroll"): "acts only on the caller's own account (identity from the verified JWT); "
        "refuses a second factor from an AAL1 session; rate limited; audited",
    ("mfa.py", "mfa_verify"): "acts only on the caller's own factor (ownership checked, GoTrue enforces it "
        "again); rate limited; audited",
    ("auth.py", "signup"): "public: generates an OTP and never reveals account existence",
    ("auth.py", "verify_signup_otp"): "public: proves control of the email via OTP",
    ("auth.py", "resend_signup_otp"): "public: rate limited per IP and per email",
    ("auth.py", "create_org_request"): "public: organization request queued for staff review",
    ("auth.py", "upload_org_request_document"): "public: validated upload for a pending request",
    ("auth.py", "login"): "public: credential exchange",
    ("auth.py", "send_otp"): "public: password reset, rate limited, uniform response",
    ("auth.py", "verify_otp"): "public: password reset OTP check",
    ("auth.py", "confirm_new_password"): "public: password reset with a verified token",
    ("auth.py", "refresh_token"): "public: refresh token exchange",
    ("auth.py", "change_password"): "self-scoped: acts only on the authenticated user",
    ("auth.py", "logout"): "self-scoped: revokes only the caller's session",
    ("auth.py", "update_me"): "self-scoped: updates only the authenticated user's account",
    ("profiles.py", "update_my_profile"): "self-scoped: profile row keyed by the caller's id",
    ("tenants.py", "create_tenant"): "self-service: creates a new tenant owned by the caller",
    ("invites.py", "accept_invite"): "token-scoped: validates the invite, email and status",
    ("digital_invitations.py", "rsvp_invitation"): "public, token-scoped: checks status, expiry and the RSVP flag",
    ("registration_forms.py", "public_register"): "public: self-registration only for published events, rate limited per IP",
    ("subscriptions.py", "calculate_custom_plan"): "POST calculation only: verified to perform no database writes",
    ("teams.py", "create_team"): "retired stub: raises 403 before any write",
    ("teams.py", "create_team_request"): "retired stub: raises 403 before any write",
    ("teams.py", "update_team"): "retired stub: raises 403 before any write",
    ("teams.py", "delete_team"): "retired stub: raises 403 before any write",
    ("checkin.py", "scan_checkin"): "retired stub: raises 410 before any write",
    ("checkin.py", "manual_checkin"): "retired stub: raises 410 before any write",
}


def _route_handlers():
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in functions.values():
            for deco in node.decorator_list:
                if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                    if deco.func.attr in {"get", "post", "put", "patch", "delete"}:
                        yield path.name, node.name, deco.func.attr, node, functions, source


def _calls_in(node) -> set[str]:
    return {
        n.func.id for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _is_guarded(node, functions, source) -> bool:
    body = ast.get_source_segment(source, node) or ""
    if any(token in body for token in GUARD_TOKENS):
        return True
    for callee in _calls_in(node):
        helper = functions.get(callee)
        if helper is not None and helper is not node:
            helper_src = ast.get_source_segment(source, helper) or ""
            if any(token in helper_src for token in GUARD_TOKENS):
                return True
    return False


def _mutating_handlers():
    for module, name, verb, node, functions, source in _route_handlers():
        if verb in MUTATING:
            yield module, name, node, functions, source


def test_inventory_finds_routes():
    # Guards against the walker silently matching nothing.
    handlers = list(_route_handlers())
    assert len(handlers) > 150, f"route walker found only {len(handlers)} handlers"


@pytest.mark.parametrize(
    "module,name,node,functions,source",
    list(_mutating_handlers()),
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_mutating_route_is_guarded(module, name, node, functions, source):
    if (module, name) in ALLOWED_UNGUARDED:
        pytest.skip(ALLOWED_UNGUARDED[(module, name)])
    assert _is_guarded(node, functions, source), (
        f"{module}:{name} changes state but shows no permission or membership check. "
        "Add a guard, or add it to ALLOWED_UNGUARDED with a reason after review."
    )


def test_allowlist_entries_still_exist():
    """A removed or renamed handler must not leave a stale exemption behind."""
    existing = {(m, n) for m, n, *_ in _route_handlers()}
    stale = sorted(key for key in ALLOWED_UNGUARDED if key not in existing)
    assert not stale, f"stale ALLOWED_UNGUARDED entries: {stale}"
