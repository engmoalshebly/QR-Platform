"""Every route must reach the database through the session its access model needs.

Two rules, both enforced by walking the real route dependency graph:

1. A route on a tenant-exempt path (no tenant context) must not use the
   RLS-enforced ``get_db``.  Under RLS it would see no rows and fail silently.
   It must use ``get_privileged_db`` and check authorization itself.

2. Every route that uses ``get_privileged_db`` must appear in
   PRIVILEGED_ROUTES with the reason.  Cross-tenant access is a security decision,
   not a convenience.
"""
import importlib
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.database import get_db, get_privileged_db
from app.main import app
from app.middleware import is_tenant_exempt

ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "routes"

PRIVILEGED_ROUTES: dict[tuple[str, str], str] = {
    ("auth.py", "change_password"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "confirm_new_password"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "create_org_request"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "get_me"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "login"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "logout"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "send_otp"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "update_me"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "verify_otp"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("auth.py", "verify_signup_otp"): "auth flow without tenant context (sign-in across memberships, OTP, own account); handler enforces its own checks",
    ("digital_invitations.py", "rsvp_invitation"): "public token-scoped access; the token must identify the invitation",
    ("digital_invitations.py", "view_invitation_public"): "public token-scoped access; the token must identify the invitation",
    ("invites.py", "accept_invite"): "token-scoped invite acceptance; email, status and expiry are verified",
    ("platform.py", "activate_custom_plan"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "activate_tenant"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "cancel_tenant"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "get_plan_limits"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "get_tenant_detail"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "get_user_detail"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "grant_platform_staff"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_all_subscriptions"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_all_tenants"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_all_users"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_audit_logs"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_platform_staff"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "plans_overview"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_analytics"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_approve_org_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_approve_team_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_create_role"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_delete_role"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_list_org_requests"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_list_permissions"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_list_team_requests"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_list_tenant_roles"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_reject_org_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_reject_team_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_stats"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "platform_update_role"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "revoke_platform_staff"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "suspend_tenant"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "update_addon"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "update_plan"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "update_plan_limits"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("registration_forms.py", "get_public_event_logo"): "public self-registration and event assets; slug-scoped and rate limited",
    ("registration_forms.py", "get_public_register_info"): "public self-registration and event assets; slug-scoped and rate limited",
    ("registration_forms.py", "public_register"): "public self-registration and event assets; slug-scoped and rate limited",
    ("subscriptions.py", "calculate_custom_plan"): "global plan catalogue or read-only calculation; no tenant data is written",
    ("subscriptions.py", "list_addons"): "global plan catalogue or read-only calculation; no tenant data is written",
    ("subscriptions.py", "list_plans"): "global plan catalogue or read-only calculation; no tenant data is written",
    ("templates.py", "upload_font"): "platform staff only (require_staff)",
    ("platform.py", "reject_custom_plan"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_pending_custom_plans"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "list_subscription_requests"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "approve_subscription_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("platform.py", "reject_subscription_request"): "platform staff console; require_staff or require_platform_superadmin is applied",
    ("tenants.py", "create_tenant"): "caller's own tenants across memberships; filtered by the authenticated user id",
    ("tenants.py", "list_my_tenants"): "caller's own tenants across memberships; filtered by the authenticated user id",
}


def _walk_dependencies(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _walk_dependencies(sub)


def _uses(route: APIRoute, dependency) -> bool:
    return any(call is dependency for call in _walk_dependencies(route.dependant))


def _api_routes():
    """Yield (full_path, route) for every route declared in app/routes."""
    for module_path in sorted(ROUTES_DIR.glob("*.py")):
        if module_path.name == "__init__.py":
            continue
        module = importlib.import_module(f"app.routes.{module_path.stem}")
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            if isinstance(route, APIRoute):
                yield f"/api/v1{route.path}", module_path.name, route


ROUTE_CASES = list(_api_routes())


def test_route_inventory_is_complete():
    assert len(ROUTE_CASES) > 150, f"only {len(ROUTE_CASES)} routes discovered"


@pytest.mark.parametrize(
    "full_path,module,route",
    [c for c in ROUTE_CASES if is_tenant_exempt(c[0])],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_exempt_routes_do_not_use_rls_session(full_path, module, route):
    if (module, route.name) in PRIVILEGED_ROUTES:
        assert _uses(route, get_privileged_db), "allowlisted but not privileged"
        return
    assert not _uses(route, get_db), (
        f"{module}:{route.name} is on tenant-exempt path {full_path} and uses get_db. "
        "Use get_privileged_db and enforce authorization in the handler."
    )


@pytest.mark.parametrize(
    "full_path,module,route",
    [c for c in ROUTE_CASES if _uses(c[2], get_privileged_db)],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_privileged_routes_are_reviewed(full_path, module, route):
    assert (module, route.name) in PRIVILEGED_ROUTES, (
        f"{module}:{route.name} ({full_path}) uses get_privileged_db without a reviewed reason."
    )
