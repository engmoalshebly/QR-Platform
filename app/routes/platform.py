"""
Platform Admin Routes — Super Admin Dashboard.
Only accessible by users with is_staff=true (super admins).
Full platform management: tenants, users, plans, subscriptions, analytics.
"""
import json
import re
import secrets
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, status, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

from app.services import access_cache
from app.auth import get_current_user, CurrentUser
from app.database import get_db, get_supabase_admin, get_supabase_client, get_privileged_db
from app.models.tenant import TenantRead
from app.models.team import TeamRequestRead, TeamRequestReview
from app.services.entitlement_service import sync_plan_cache
from app.services.subscription_state import invalidate_subscription_state
from app.services.renewal import check_same_plan_extension, days_left, renewal_valid_until
from app.services.audit_service import log_audit
from app.services.staff_service import require_platform_superadmin, require_staff
from app.services.provisioning_service import (
    provision_tenant_manual,
    ensure_linked_institution_workspace,
    ensure_team_manager_role,
)
from app.services.email_service import (
    send_subscription_renewed_email,
    send_org_request_approved, send_org_request_rejected,
    send_subscription_upgraded_email, send_subscription_request_rejected,
)
from app.services.notification_service import notify_tenant_managers
from app.services.secret_box import decrypt_secret
from app.security import get_client_ip
from app.routes.roles import PermissionRead, RoleRead, RoleCreate, RoleUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["Platform Admin"])


async def _tenant_owner_contact(db: AsyncSession, tenant_id) -> Optional[dict]:
    """Best-effort email + name for a tenant's active owner, for billing
    notifications. Returns None if there is no owner with a known email."""
    row = (await db.execute(text("""
        SELECT u.email, COALESCE(p.full_name, u.email) AS full_name
        FROM memberships m
        JOIN auth.users u ON u.id = m.user_id
        LEFT JOIN profiles p ON p.id = m.user_id
        WHERE m.tenant_id = :tid AND m.role = 'owner' AND m.status = 'active'
        LIMIT 1
    """), {"tid": str(tenant_id)})).mappings().first()
    return dict(row) if row and row["email"] else None


async def _safe(db, sql, params=None):
    """Run a query safely, returning None on error."""
    try:
        return await db.execute(text(sql), params or {})
    except Exception:
        await db.rollback()
        return None


async def _resolve_workspace_scope(db: AsyncSession, tenant_id: UUID) -> tuple[str, str, bool]:
    """Resolve a platform tenant to its commercial workspace group.

    Organizer workspaces and the companion institution workspace are kept
    separate at the data/permission layer.  Platform administration, billing
    and lifecycle actions, however, must treat the pair as one organization.
    The tuple is ``(canonical_organizer_id, companion_id, is_linked)``.  For a
    standalone institution both ids are intentionally the same.
    """
    result = await db.execute(
        text("""
            SELECT organizer_tenant_id::text, institution_tenant_id::text
            FROM workspace_links
            WHERE (organizer_tenant_id = :tenant_id OR institution_tenant_id = :tenant_id)
              AND status = 'active'
            LIMIT 1
        """),
        {"tenant_id": str(tenant_id)},
    )
    row = result.mappings().first()
    if row:
        return str(row["organizer_tenant_id"]), str(row["institution_tenant_id"]), True
    return str(tenant_id), str(tenant_id), False


# ══════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════

class PlatformTenantRead(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    plan: str
    workspace_type: str = "institution"
    created_by: Optional[UUID] = None
    metadata: Optional[dict] = None
    expires_at: Optional[str] = None
    created_at: str
    updated_at: str
    members_count: Optional[int] = None
    linked_tenant_id: Optional[UUID] = None
    linked_tenant_name: Optional[str] = None
    is_workspace_group: bool = False


class TenantStatusUpdate(BaseModel):
    status: str  # active, suspended, cancelled


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    price_monthly: Optional[float] = None
    price_yearly: Optional[float] = None
    is_active: Optional[bool] = None
    is_popular: Optional[bool] = None
    badge_color: Optional[str] = None


class PlanLimitItem(BaseModel):
    key: str
    value: int
    period: str = "none"


class AddonUpdate(BaseModel):
    label_ar: Optional[str] = None
    label_en: Optional[str] = None
    unit_ar: Optional[str] = None
    unit_en: Optional[str] = None
    icon: Optional[str] = None
    price_per_unit: Optional[float] = None
    is_active: Optional[bool] = None


class PlatformStaffGrant(BaseModel):
    """Promote an existing authenticated account to platform administrator."""

    email: EmailStr


class PlatformStaffRead(BaseModel):
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    is_staff: bool = True


class CustomPlanActivation(BaseModel):
    """Evidence captured by a platform administrator after payment validation."""

    payment_reference: str = Field(min_length=3, max_length=120)
    valid_until: datetime


class SubscriptionRequestApproval(BaseModel):
    """Evidence captured by staff after verifying payment out of band
    (bank transfer, cash, etc.) for a standard-plan subscription request."""

    payment_reference: str = Field(min_length=3, max_length=120)
    valid_until: datetime


class RequestReview(BaseModel):
    """A staff note, required by the frontend when rejecting, optional otherwise."""

    note: Optional[str] = None


async def _platform_staff_count_for_update(db: AsyncSession) -> int:
    """Lock the staff rows before a promotion/demotion decision.

    The lock prevents two concurrent demotions from both believing that another
    administrator still exists.
    """
    rows = await db.execute(text("SELECT id FROM profiles WHERE is_staff = true FOR UPDATE"))
    return len(rows.all())


# ══════════════════════════════════════════════════
# COMPREHENSIVE ANALYTICS
# ══════════════════════════════════════════════════

@router.get("/analytics")
async def platform_analytics(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Comprehensive platform analytics for super admin dashboard."""
    analytics = {}

    # ── KPIs ──
    r = await _safe(db, """
        WITH canonical_tenants AS (
            SELECT t.*
            FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM workspace_links wl
                WHERE wl.institution_tenant_id = t.id AND wl.status = 'active'
            )
        )
        SELECT
            (SELECT COUNT(*) FROM canonical_tenants) AS total_tenants,
            (SELECT COUNT(*) FROM canonical_tenants WHERE status = 'active') AS active_tenants,
            (SELECT COUNT(*) FROM canonical_tenants WHERE status = 'trial') AS trial_tenants,
            (SELECT COUNT(*) FROM canonical_tenants WHERE status = 'suspended') AS suspended_tenants,
            (SELECT COUNT(*) FROM canonical_tenants WHERE status = 'cancelled') AS cancelled_tenants,
            (SELECT COUNT(*) FROM canonical_tenants WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_tenants_30d,
            (SELECT COUNT(*) FROM canonical_tenants WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS new_tenants_7d,
            (SELECT COUNT(*) FROM profiles) AS total_users,
            (SELECT COUNT(*) FROM profiles WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_users_30d,
            (SELECT COUNT(*) FROM memberships WHERE status = 'active') AS total_active_memberships,
            (SELECT COUNT(*) FROM subscriptions WHERE status = 'active') AS active_subscriptions,
            (SELECT COUNT(*) FROM events) AS total_events,
            (SELECT COUNT(*) FROM invitations) AS total_invitations,
            (SELECT COUNT(*) FROM guests) AS total_guests
    """)
    if r:
        analytics["kpis"] = dict(r.mappings().first())
    else:
        analytics["kpis"] = {}

    # ── Revenue (MRR / ARR) ──
    r = await _safe(db, """
        SELECT
            COALESCE(SUM(p.price_monthly), 0) AS mrr,
            COALESCE(SUM(p.price_monthly * 12), 0) AS arr,
            COALESCE(AVG(p.price_monthly), 0) AS avg_revenue_per_tenant,
            COUNT(*) AS paying_count
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.status = 'active' AND p.price_monthly > 0
    """)
    if r:
        row = r.mappings().first()
        analytics["revenue"] = {
            "mrr": float(row["mrr"]),
            "arr": float(row["arr"]),
            "avg_revenue_per_tenant": round(float(row["avg_revenue_per_tenant"]), 2),
            "paying_tenants": row["paying_count"],
        }
    else:
        analytics["revenue"] = {"mrr": 0, "arr": 0, "avg_revenue_per_tenant": 0, "paying_tenants": 0}

    # ── Plan distribution ──
    r = await _safe(db, """
        SELECT p.code AS plan, p.name AS plan_name, p.badge_color, COUNT(s.id) AS count
        FROM plans p
        LEFT JOIN subscriptions s ON s.plan_id = p.id AND s.status = 'active'
        GROUP BY p.code, p.name, p.badge_color, p.sort_order
        ORDER BY p.sort_order
    """)
    if r:
        analytics["plan_distribution"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["plan_distribution"] = []

    # ── Status distribution ──
    r = await _safe(db, """
        WITH canonical_tenants AS (
            SELECT t.* FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM workspace_links wl
                WHERE wl.institution_tenant_id = t.id AND wl.status = 'active'
            )
        )
        SELECT status, COUNT(*) AS count
        FROM canonical_tenants
        GROUP BY status
        ORDER BY count DESC
    """)
    if r:
        analytics["status_distribution"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["status_distribution"] = []

    # ── Trend (last 30 days) ──
    r = await _safe(db, """
        WITH canonical_tenants AS (
            SELECT t.* FROM tenants t
            WHERE NOT EXISTS (
                SELECT 1 FROM workspace_links wl
                WHERE wl.institution_tenant_id = t.id AND wl.status = 'active'
            )
        )
        SELECT d::date AS date,
               COALESCE(t.cnt, 0) AS new_tenants,
               COALESCE(u.cnt, 0) AS new_users
        FROM generate_series(CURRENT_DATE - 29, CURRENT_DATE, '1 day') d
        LEFT JOIN (
            SELECT created_at::date AS d, COUNT(*) AS cnt FROM canonical_tenants
            WHERE created_at >= CURRENT_DATE - 29
            GROUP BY created_at::date
        ) t ON t.d = d.d
        LEFT JOIN (
            SELECT created_at::date AS d, COUNT(*) AS cnt FROM profiles
            WHERE created_at >= CURRENT_DATE - 29
            GROUP BY created_at::date
        ) u ON u.d = d.d
        ORDER BY d
    """)
    if r:
        analytics["trend_30d"] = [
            {"date": str(row["date"]), "new_tenants": row["new_tenants"], "new_users": row["new_users"]}
            for row in r.mappings().all()
        ]
    else:
        analytics["trend_30d"] = []

    # ── Recent tenants ──
    r = await _safe(db, """
        SELECT t.id::text, t.slug, t.name, t.status, t.plan,
               t.created_at::text,
               (SELECT COUNT(DISTINCT m.user_id) FROM memberships m
                WHERE m.tenant_id IN (t.id, COALESCE(wl.institution_tenant_id, t.id))
                  AND m.status = 'active') AS members_count
        FROM tenants t
        LEFT JOIN workspace_links wl
          ON wl.organizer_tenant_id = t.id AND wl.status = 'active'
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_links child_link
            WHERE child_link.institution_tenant_id = t.id AND child_link.status = 'active'
        )
        ORDER BY t.created_at DESC
        LIMIT 10
    """)
    if r:
        analytics["recent_tenants"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["recent_tenants"] = []

    # ── Top tenants by activity ──
    r = await _safe(db, """
        SELECT t.id::text, t.slug, t.name, t.plan,
               (SELECT COUNT(*) FROM events e WHERE e.tenant_id IN (t.id, COALESCE(wl.institution_tenant_id, t.id))) AS events_count,
               (SELECT COUNT(*) FROM invitations i WHERE i.tenant_id IN (t.id, COALESCE(wl.institution_tenant_id, t.id))) AS invitations_count,
               (SELECT COUNT(DISTINCT m.user_id) FROM memberships m
                WHERE m.tenant_id IN (t.id, COALESCE(wl.institution_tenant_id, t.id))
                  AND m.status = 'active') AS members_count
        FROM tenants t
        LEFT JOIN workspace_links wl
          ON wl.organizer_tenant_id = t.id AND wl.status = 'active'
        WHERE t.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM workspace_links child_link
              WHERE child_link.institution_tenant_id = t.id AND child_link.status = 'active'
          )
        ORDER BY invitations_count DESC
        LIMIT 10
    """)
    if r:
        analytics["top_tenants"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["top_tenants"] = []

    return analytics


# ══════════════════════════════════════════════════
# TENANTS MANAGEMENT
# ══════════════════════════════════════════════════

@router.get("/tenants", response_model=list[PlatformTenantRead])
async def list_all_tenants(
    status_filter: Optional[str] = Query(None, alias="status"),
    plan: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List all tenants on the platform. Staff only."""
    # A linked organizer and its companion institution are one commercial
    # account.  Keep the underlying workspaces separate for authorization and
    # event ownership, but return a single canonical row to platform admins.
    query = """
        SELECT t.id, t.slug, t.name, t.status, t.plan, t.workspace_type, t.created_by,
               t.metadata, t.expires_at::text, t.created_at::text, t.updated_at::text,
               wl.institution_tenant_id AS linked_tenant_id,
               linked.name AS linked_tenant_name,
               (wl.id IS NOT NULL) AS is_workspace_group,
               (
                   SELECT COUNT(DISTINCT m.user_id)
                   FROM memberships m
                   WHERE m.status = 'active'
                     AND m.tenant_id IN (t.id, COALESCE(wl.institution_tenant_id, t.id))
               ) AS members_count
        FROM tenants t
        LEFT JOIN workspace_links wl
          ON wl.organizer_tenant_id = t.id AND wl.status = 'active'
        LEFT JOIN tenants linked ON linked.id = wl.institution_tenant_id
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_links child_link
            WHERE child_link.institution_tenant_id = t.id
              AND child_link.status = 'active'
        )
    """
    params: dict = {"limit": limit, "offset": offset}

    if status_filter:
        query += " AND t.status = :status"
        params["status"] = status_filter

    if plan:
        query += " AND t.plan = :plan"
        params["plan"] = plan

    if search:
        query += " AND (t.name ILIKE :search OR t.slug ILIKE :search OR linked.name ILIKE :search OR linked.slug ILIKE :search)"
        params["search"] = f"%{search}%"

    query += " ORDER BY t.created_at DESC LIMIT :limit OFFSET :offset"

    result = await db.execute(text(query), params)
    rows = result.mappings().all()
    return [PlatformTenantRead(**dict(r)) for r in rows]


@router.get("/tenants/{tenant_id}")
async def get_tenant_detail(
    tenant_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Get the unified detail view for one commercial organization.

    A linked organizer/institution pair remains two technical workspaces, but
    it is intentionally exposed as a single organization to platform staff.
    Either workspace id resolves to the organizer (canonical) record.
    """
    link_result = await db.execute(
        text("""
            SELECT wl.organizer_tenant_id::text, wl.institution_tenant_id::text,
                   wl.billing_tenant_id::text, institution.name AS institution_name
            FROM workspace_links wl
            JOIN tenants institution ON institution.id = wl.institution_tenant_id
            WHERE (wl.organizer_tenant_id = :tenant_id OR wl.institution_tenant_id = :tenant_id)
              AND wl.status = 'active'
            LIMIT 1
        """),
        {"tenant_id": str(tenant_id)},
    )
    workspace_link = link_result.mappings().first()
    canonical_id = str(workspace_link["organizer_tenant_id"]) if workspace_link else str(tenant_id)
    linked_id = str(workspace_link["institution_tenant_id"]) if workspace_link else canonical_id
    billing_id = str(workspace_link["billing_tenant_id"]) if workspace_link else canonical_id
    scoped_params = {"primary_id": canonical_id, "linked_id": linked_id}

    # Tenant info and usage are aggregated across the linked pair.
    result = await db.execute(
        text("""
            SELECT t.id::text, t.slug, t.name, t.status, t.plan, t.workspace_type, t.created_by::text,
                   t.metadata, t.expires_at::text, t.created_at::text, t.updated_at::text,
                   (SELECT COUNT(DISTINCT m.user_id) FROM memberships m
                       WHERE m.tenant_id IN (:primary_id, :linked_id) AND m.status = 'active') AS members_count,
                   (SELECT COUNT(*) FROM events e WHERE e.tenant_id IN (:primary_id, :linked_id)) AS events_count,
                   (SELECT COUNT(*) FROM invitations i WHERE i.tenant_id IN (:primary_id, :linked_id)) AS invitations_count,
                   (SELECT COUNT(*) FROM guests g WHERE g.tenant_id IN (:primary_id, :linked_id)) AS guests_count
            FROM tenants t WHERE t.id = :primary_id
        """),
        scoped_params,
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="المستأجر غير موجود")

    # Subscription info
    sub_result = await db.execute(
        text("""
            SELECT s.status::text AS sub_status, p.code AS plan_code, p.name AS plan_name,
                   p.price_monthly, s.current_period_end::text, s.trial_ends_at::text
            FROM subscriptions s JOIN plans p ON p.id = s.plan_id
            WHERE s.tenant_id = :billing_id ORDER BY s.created_at DESC LIMIT 1
        """),
        {"billing_id": billing_id},
    )
    sub = sub_result.mappings().first()

    # Members
    members_result = await db.execute(
        text("""
            SELECT p.id::text AS user_id, p.full_name, p.avatar_url,
                   STRING_AGG(DISTINCT m.role::text, ' · ') AS role,
                   CASE WHEN BOOL_OR(m.status::text = 'active') THEN 'active'
                        ELSE MAX(m.status::text) END AS status,
                   MIN(m.created_at)::text AS created_at,
                   COALESCE(
                       ARRAY_AGG(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL),
                       ARRAY[]::text[]
                   ) AS assigned_roles
            FROM memberships m JOIN profiles p ON p.id = m.user_id
            LEFT JOIN membership_roles mr
                ON mr.tenant_id = m.tenant_id AND mr.user_id = m.user_id
            LEFT JOIN roles r ON r.id = mr.role_id
            WHERE m.tenant_id IN (:primary_id, :linked_id)
            GROUP BY p.id, p.full_name, p.avatar_url
            ORDER BY MIN(m.created_at)
        """),
        scoped_params,
    )

    # The detail page is deliberately scoped to a single tenant.  It gives a
    # platform administrator an operational picture without exposing records
    # from any other workspace.
    analytics_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS events_total,
                COUNT(*) FILTER (WHERE e.status::text IN ('draft', 'planning')) AS events_draft,
                COUNT(*) FILTER (WHERE e.status::text IN ('published', 'active')) AS events_live,
                COUNT(*) FILTER (WHERE e.start_date >= date_trunc('day', now())) AS events_upcoming,
                COALESCE(SUM(e.vip_quota), 0) AS vip_capacity,
                COALESCE(SUM(e.normal_quota), 0) AS normal_capacity,
                (SELECT COUNT(*) FROM invitations i WHERE i.tenant_id IN (:primary_id, :linked_id)) AS invitations_total,
                (SELECT COUNT(*) FROM guests g WHERE g.tenant_id IN (:primary_id, :linked_id)) AS guests_total,
                (SELECT COUNT(*) FROM audit_logs a
                    WHERE a.tenant_id IN (:primary_id, :linked_id)
                      AND a.created_at >= now() - interval '30 days') AS activity_30d
            FROM events e
            WHERE e.tenant_id IN (:primary_id, :linked_id) AND e.deleted_at IS NULL
        """),
        scoped_params,
    )

    events_result = await db.execute(
        text("""
            SELECT e.id::text, COALESCE(NULLIF(e.title_ar, ''), e.title) AS title,
                   e.status::text, e.start_date::text, e.end_date::text,
                   COALESCE(NULLIF(e.venue_name_ar, ''), e.venue_name, e.venue_city) AS location,
                   COUNT(i.id) AS invitations_count
            FROM events e
            LEFT JOIN invitations i ON i.event_id = e.id
            WHERE e.tenant_id IN (:primary_id, :linked_id) AND e.deleted_at IS NULL
            GROUP BY e.id, e.title_ar, e.title, e.status, e.start_date, e.end_date,
                     e.venue_name_ar, e.venue_name, e.venue_city
            ORDER BY e.start_date DESC
            LIMIT 8
        """),
        scoped_params,
    )

    roles_result = await db.execute(
        text("""
            SELECT r.id::text, r.tenant_id::text, r.name, r.description,
                   r.is_system_role, r.created_at::text,
                   CASE WHEN r.tenant_id = :primary_id THEN 'organizer' ELSE 'institution' END AS workspace_type,
                   COALESCE(ARRAY_AGG(rp.permission_key) FILTER (WHERE rp.permission_key IS NOT NULL),
                            ARRAY[]::text[]) AS permissions,
                   COUNT(DISTINCT mr.user_id) AS members_count
            FROM roles r
            LEFT JOIN role_permissions rp ON rp.role_id = r.id
            LEFT JOIN membership_roles mr ON mr.role_id = r.id
            WHERE r.tenant_id IN (:primary_id, :linked_id)
            GROUP BY r.id
            ORDER BY r.is_system_role DESC, r.name
        """),
        scoped_params,
    )

    activity_result = await db.execute(
        text("""
            SELECT a.id::text, a.action, a.resource_type, a.resource_id,
                   a.metadata, a.created_at::text,
                   p.full_name AS actor_name
            FROM audit_logs a
            LEFT JOIN profiles p ON p.id = a.actor_user_id
            WHERE a.tenant_id IN (:primary_id, :linked_id)
            ORDER BY a.created_at DESC
            LIMIT 12
        """),
        scoped_params,
    )

    tenant = dict(row)
    tenant["linked_tenant_id"] = str(workspace_link["institution_tenant_id"]) if workspace_link else None
    tenant["linked_tenant_name"] = str(workspace_link["institution_name"]) if workspace_link else None
    tenant["is_workspace_group"] = bool(workspace_link)

    return {
        "tenant": tenant,
        "workspace_group": {
            "is_linked": bool(workspace_link),
            "organizer_tenant_id": canonical_id,
            "institution_tenant_id": str(workspace_link["institution_tenant_id"]) if workspace_link else None,
            "institution_name": str(workspace_link["institution_name"]) if workspace_link else None,
            "billing_tenant_id": billing_id,
        },
        "subscription": dict(sub) if sub else None,
        "members": [dict(r) for r in members_result.mappings().all()],
        "analytics": dict(analytics_result.mappings().first()),
        "recent_events": [dict(r) for r in events_result.mappings().all()],
        "roles": [dict(r) for r in roles_result.mappings().all()],
        "recent_activity": [dict(r) for r in activity_result.mappings().all()],
    }


class PlatformRsvpUpdate(BaseModel):
    enabled: bool


@router.get("/tenants/{tenant_id}/features/rsvp")
async def get_platform_rsvp(
    tenant_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    canonical_id, linked_id, _ = await _resolve_workspace_scope(db, tenant_id)
    from app.services.feature_service import check_feature_flag
    values = [await check_feature_flag(db, UUID(tid), "rsvp") for tid in dict.fromkeys([canonical_id, linked_id])]
    return {"enabled": all(values), "mixed": len(set(values)) > 1}


@router.put("/tenants/{tenant_id}/features/rsvp")
async def update_platform_rsvp(
    tenant_id: UUID, body: PlatformRsvpUpdate, request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    canonical_id, linked_id, is_linked = await _resolve_workspace_scope(db, tenant_id)
    for scoped_id in dict.fromkeys([canonical_id, linked_id]):
        await db.execute(text("""
            INSERT INTO feature_flags (tenant_id, flag_key, enabled)
            VALUES (:tid, 'rsvp', :enabled)
            ON CONFLICT (tenant_id, flag_key)
            DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()
        """), {"tid": scoped_id, "enabled": body.enabled})
        await log_audit(db, tenant_id=UUID(scoped_id), actor_user_id=user.id,
                        action="feature.toggle", resource_type="feature_flag",
                        metadata={"flag_key": "rsvp", "enabled": body.enabled, "platform": True},
                        ip_address=get_client_ip(request))
    await db.commit()
    return {"enabled": body.enabled, "mixed": False, "linked": is_linked}


@router.get("/tenants/{tenant_id}/features/whatsapp")
async def get_platform_whatsapp(
    tenant_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    canonical_id, linked_id, _ = await _resolve_workspace_scope(db, tenant_id)
    from app.services.feature_service import check_feature_flag
    values = [await check_feature_flag(db, UUID(tid), "whatsapp_delivery") for tid in dict.fromkeys([canonical_id, linked_id])]
    return {"enabled": all(values), "mixed": len(set(values)) > 1}


@router.put("/tenants/{tenant_id}/features/whatsapp")
async def update_platform_whatsapp(
    tenant_id: UUID, body: PlatformRsvpUpdate, request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    canonical_id, linked_id, is_linked = await _resolve_workspace_scope(db, tenant_id)
    for scoped_id in dict.fromkeys([canonical_id, linked_id]):
        await db.execute(text("""
            INSERT INTO feature_flags (tenant_id, flag_key, enabled)
            VALUES (:tid, 'whatsapp_delivery', :enabled)
            ON CONFLICT (tenant_id, flag_key)
            DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()
        """), {"tid": scoped_id, "enabled": body.enabled})
        await log_audit(db, tenant_id=UUID(scoped_id), actor_user_id=user.id,
                        action="feature.toggle", resource_type="feature_flag",
                        metadata={"flag_key": "whatsapp_delivery", "enabled": body.enabled, "platform": True},
                        ip_address=get_client_ip(request))
    await db.commit()
    return {"enabled": body.enabled, "mixed": False, "linked": is_linked}


@router.post("/tenants/{tenant_id}/suspend")
async def suspend_tenant(
    tenant_id: UUID, request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Suspend a commercial organization and all of its linked workspaces."""
    canonical_id, linked_id, is_linked = await _resolve_workspace_scope(db, tenant_id)
    result = await db.execute(
        text("""
            UPDATE tenants SET status = 'suspended', updated_at = now()
            WHERE id IN (:primary_id, :linked_id) AND status != 'suspended'
            RETURNING id
        """),
        {"primary_id": canonical_id, "linked_id": linked_id},
    )
    updated_ids = [str(row[0]) for row in result.all()]
    for updated_id in updated_ids:
        access_cache.invalidate_tenant(updated_id)
    if not updated_ids:
        raise HTTPException(status_code=404, detail="المستأجر غير موجود أو معلّق مسبقاً")
    await log_audit(db, tenant_id=UUID(canonical_id), actor_user_id=user.id,
                    action="tenant.suspend", resource_type="workspace_group", resource_id=canonical_id,
                    metadata={"linked_workspace": is_linked, "updated_tenant_ids": updated_ids},
                    ip_address=get_client_ip(request))
    await db.commit()
    return {"message": "تم تعليق المؤسسة ومساحاتها المرتبطة بنجاح", "status": "suspended", "updated_tenant_ids": updated_ids}


@router.post("/tenants/{tenant_id}/activate")
async def activate_tenant(
    tenant_id: UUID, request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Re-activate a commercial organization and all linked workspaces."""
    canonical_id, linked_id, is_linked = await _resolve_workspace_scope(db, tenant_id)
    result = await db.execute(
        text("""
            UPDATE tenants SET status = 'active', updated_at = now()
            WHERE id IN (:primary_id, :linked_id) AND status IN ('suspended', 'cancelled')
            RETURNING id
        """),
        {"primary_id": canonical_id, "linked_id": linked_id},
    )
    updated_ids = [str(row[0]) for row in result.all()]
    for updated_id in updated_ids:
        access_cache.invalidate_tenant(updated_id)
    if not updated_ids:
        raise HTTPException(status_code=404, detail="المستأجر غير موجود أو نشط مسبقاً")
    await log_audit(db, tenant_id=UUID(canonical_id), actor_user_id=user.id,
                    action="tenant.activate", resource_type="workspace_group", resource_id=canonical_id,
                    metadata={"linked_workspace": is_linked, "updated_tenant_ids": updated_ids},
                    ip_address=get_client_ip(request))
    await db.commit()
    return {"message": "تم تفعيل المؤسسة ومساحاتها المرتبطة بنجاح", "status": "active", "updated_tenant_ids": updated_ids}


@router.post("/tenants/{tenant_id}/cancel")
async def cancel_tenant(
    tenant_id: UUID, request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Cancel a commercial organization and all linked workspaces."""
    canonical_id, linked_id, is_linked = await _resolve_workspace_scope(db, tenant_id)
    result = await db.execute(
        text("""
            UPDATE tenants SET status = 'cancelled', updated_at = now()
            WHERE id IN (:primary_id, :linked_id) AND status != 'cancelled'
            RETURNING id
        """),
        {"primary_id": canonical_id, "linked_id": linked_id},
    )
    updated_ids = [str(row[0]) for row in result.all()]
    for updated_id in updated_ids:
        access_cache.invalidate_tenant(updated_id)
    if not updated_ids:
        raise HTTPException(status_code=404, detail="المستأجر غير موجود أو ملغى مسبقاً")
    await log_audit(db, tenant_id=UUID(canonical_id), actor_user_id=user.id,
                    action="tenant.cancel", resource_type="workspace_group", resource_id=canonical_id,
                    metadata={"linked_workspace": is_linked, "updated_tenant_ids": updated_ids},
                    ip_address=get_client_ip(request))
    await db.commit()
    return {"message": "تم إلغاء المؤسسة ومساحاتها المرتبطة", "status": "cancelled", "updated_tenant_ids": updated_ids}


# ══════════════════════════════════════════════════
# USERS MANAGEMENT
# ══════════════════════════════════════════════════

@router.get("/users")
async def list_all_users(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List all users on the platform. Staff only."""
    query = """
        SELECT p.id::text, p.full_name, p.avatar_url, p.is_staff,
               p.created_at::text, p.last_login_at::text,
               (SELECT COUNT(*) FROM memberships m WHERE m.user_id = p.id AND m.status = 'active') AS tenants_count,
               (SELECT au.email FROM auth.users au WHERE au.id = p.id) AS email
        FROM profiles p
        WHERE 1=1
    """
    params: dict = {"limit": limit, "offset": offset}

    if search:
        query += " AND (p.full_name ILIKE :search OR EXISTS (SELECT 1 FROM auth.users au WHERE au.id = p.id AND au.email ILIKE :search))"
        params["search"] = f"%{search}%"

    query += " ORDER BY p.created_at DESC LIMIT :limit OFFSET :offset"
    result = await db.execute(text(query), params)
    rows = result.mappings().all()

    # Total count
    count_query = "SELECT COUNT(*) FROM profiles"
    count_result = await db.execute(text(count_query))
    total = count_result.scalar()

    return {"users": [dict(r) for r in rows], "total": total}


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Get user detail with all their tenant memberships."""
    result = await db.execute(
        text("""
            SELECT p.id::text, p.full_name, p.avatar_url, p.is_staff,
                   p.created_at::text, p.last_login_at::text,
                   (SELECT au.email FROM auth.users au WHERE au.id = p.id) AS email
            FROM profiles p WHERE p.id = :uid
        """),
        {"uid": str(user_id)},
    )
    profile = result.mappings().first()
    if not profile:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    # Get all memberships
    memberships_result = await db.execute(
        text("""
            SELECT t.id::text AS tenant_id, t.name AS tenant_name, t.slug,
                   m.role::text, m.status::text, m.created_at::text
            FROM memberships m JOIN tenants t ON t.id = m.tenant_id
            WHERE m.user_id = :uid ORDER BY m.created_at
        """),
        {"uid": str(user_id)},
    )

    return {
        "user": dict(profile),
        "memberships": [dict(r) for r in memberships_result.mappings().all()],
    }


@router.get("/staff", response_model=list[PlatformStaffRead])
async def list_platform_staff(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Return platform administrators only; tenant roles are intentionally excluded."""
    result = await db.execute(text("""
        SELECT p.id, au.email, p.full_name, p.is_staff
        FROM profiles p
        JOIN auth.users au ON au.id = p.id
        WHERE p.is_staff = true
        ORDER BY p.created_at ASC
    """))
    return [PlatformStaffRead(**dict(row)) for row in result.mappings().all()]


@router.post("/staff", response_model=PlatformStaffRead, status_code=status.HTTP_201_CREATED)
async def grant_platform_staff(
    body: PlatformStaffGrant,
    request: Request,
    user: CurrentUser = Depends(require_platform_superadmin),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Grant platform administration to an existing account, with an audit trail.

    This endpoint never creates a password or an institution; accounts must be
    created through the normal account/invitation process first.
    """
    email = str(body.email).lower().strip()
    result = await db.execute(text("""
        SELECT au.id, au.email, p.full_name, COALESCE(p.is_staff, false) AS is_staff
        FROM auth.users au
        LEFT JOIN profiles p ON p.id = au.id
        WHERE lower(au.email) = :email
        FOR UPDATE OF au
    """), {"email": email})
    target = result.mappings().first()
    if not target:
        raise HTTPException(status_code=404, detail="يجب إنشاء حساب للمستخدم أولاً قبل منحه إدارة المنصة")

    if not target["is_staff"]:
        await db.execute(text("""
            INSERT INTO profiles (id, full_name, is_staff, status)
            VALUES (:id, COALESCE(:name, ''), true, 'active')
            ON CONFLICT (id) DO UPDATE SET is_staff = true, updated_at = now()
        """), {"id": str(target["id"]), "name": target["full_name"]})
        await log_audit(
            db,
            tenant_id=None,
            actor_user_id=user.id,
            action="platform.staff.grant",
            resource_type="profile",
            resource_id=str(target["id"]),
            new_values={"is_staff": True, "email": email},
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()

    return PlatformStaffRead(
        id=target["id"], email=target["email"], full_name=target["full_name"], is_staff=True
    )


@router.delete("/staff/{staff_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_platform_staff(
    staff_user_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_platform_superadmin),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Revoke platform access without touching the user's tenant memberships."""
    if staff_user_id == user.id:
        raise HTTPException(status_code=400, detail="لا يمكنك سحب صلاحية مدير المنصة من حسابك الحالي")

    staff_count = await _platform_staff_count_for_update(db)
    target = await db.execute(text("""
        SELECT p.id, au.email
        FROM profiles p JOIN auth.users au ON au.id = p.id
        WHERE p.id = :id AND p.is_staff = true
        FOR UPDATE
    """), {"id": str(staff_user_id)})
    row = target.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="مدير المنصة غير موجود")
    if staff_count <= 1:
        raise HTTPException(status_code=409, detail="لا يمكن سحب آخر مدير منصة")

    await db.execute(text("UPDATE profiles SET is_staff = false, updated_at = now() WHERE id = :id"), {"id": str(staff_user_id)})
    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=user.id,
        action="platform.staff.revoke",
        resource_type="profile",
        resource_id=str(staff_user_id),
        old_values={"is_staff": True, "email": row["email"]},
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()


# ══════════════════════════════════════════════════
# SUBSCRIPTIONS & REVENUE
# ══════════════════════════════════════════════════

@router.get("/subscriptions")
async def list_all_subscriptions(
    status_filter: Optional[str] = Query(None, alias="status"),
    plan_code: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List all subscriptions across the platform."""
    query = """
        SELECT s.id::text, s.tenant_id::text, t.name AS tenant_name, t.slug AS tenant_slug,
               s.status::text AS sub_status, p.code AS plan_code, p.name AS plan_name,
               p.price_monthly, s.current_period_start::text, s.current_period_end::text,
               s.trial_ends_at::text, s.created_at::text
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        JOIN tenants t ON t.id = s.tenant_id
        WHERE 1=1
    """
    params: dict = {"limit": limit, "offset": offset}

    if status_filter:
        query += " AND s.status = :status"
        params["status"] = status_filter

    if plan_code:
        query += " AND p.code = :plan_code"
        params["plan_code"] = plan_code

    query += " ORDER BY s.created_at DESC LIMIT :limit OFFSET :offset"
    result = await db.execute(text(query), params)
    return [dict(r) for r in result.mappings().all()]


# ══════════════════════════════════════════════════
# AUDIT LOGS (Platform-wide)
# ══════════════════════════════════════════════════

@router.get("/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List audit logs across the entire platform."""
    query = """
        SELECT a.id::text, a.tenant_id::text, t.name AS tenant_name,
               a.actor_user_id::text, p.full_name AS actor_name,
               a.action, a.resource_type, a.resource_id,
               a.metadata, a.ip_address::text, a.created_at::text
        FROM audit_logs a
        LEFT JOIN tenants t ON t.id = a.tenant_id
        LEFT JOIN profiles p ON p.id = a.actor_user_id
        WHERE 1=1
    """
    params: dict = {"limit": limit, "offset": offset}

    if action:
        query += " AND a.action ILIKE :action"
        params["action"] = f"%{action}%"

    if tenant_id:
        query += " AND a.tenant_id = :tid"
        params["tid"] = tenant_id

    query += " ORDER BY a.created_at DESC LIMIT :limit OFFSET :offset"
    result = await db.execute(text(query), params)
    return [dict(r) for r in result.mappings().all()]


# ══════════════════════════════════════════════════
# PLANS MANAGEMENT
# ══════════════════════════════════════════════════

@router.get("/plans-overview")
async def plans_overview(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Get all plans with subscriber counts and addon pricing."""
    # Plans with counts
    plans_result = await db.execute(text("""
        SELECT p.id::text, p.code, p.name, p.description, p.subtitle,
               p.price_monthly, p.price_yearly, p.currency,
               p.badge_color, p.is_popular, p.is_active, p.sort_order,
               COUNT(s.id) FILTER (WHERE s.status = 'active') AS active_subscribers,
               COUNT(s.id) AS total_subscribers
        FROM plans p
        LEFT JOIN subscriptions s ON s.plan_id = p.id
        GROUP BY p.id
        ORDER BY p.sort_order
    """))
    plans = [dict(r) for r in plans_result.mappings().all()]

    # Addons
    addons_result = await db.execute(text("""
        SELECT id::text, key, label_ar, label_en, unit_ar, icon,
               price_per_unit, step, category, sort_order
        FROM plan_addons WHERE is_active = true ORDER BY sort_order
    """))
    addons = [dict(r) for r in addons_result.mappings().all()]

    # Custom plans count
    custom_result = await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE status = 'active') AS active_custom,
               COUNT(*) AS total_custom
        FROM custom_plans
    """))
    custom = dict(custom_result.mappings().first())

    return {"plans": plans, "addons": addons, "custom_plans": custom}


# ── Platform Stats (legacy, kept for backward compatibility) ──
@router.post("/custom-plans/{custom_plan_id}/activate")
async def activate_custom_plan(
    custom_plan_id: UUID,
    body: CustomPlanActivation,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Activate a quoted custom plan after staff payment verification.

    Tenant administrators can request and price a custom plan, but cannot
    grant themselves commercial entitlements. Activation is staff-only,
    auditable, and always has a defined end date.
    """
    valid_until = body.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="valid_until must be in the future")

    plan_result = await db.execute(
        text("""
            SELECT id, tenant_id, status, name
            FROM custom_plans
            WHERE id = :plan_id
            FOR UPDATE
        """),
        {"plan_id": str(custom_plan_id)},
    )
    custom_plan = plan_result.mappings().first()
    if not custom_plan:
        raise HTTPException(status_code=404, detail="Custom plan not found")
    if custom_plan["status"] not in {"draft", "pending_review", "expired"}:
        raise HTTPException(status_code=409, detail="Custom plan is not awaiting activation")

    tenant_id = str(custom_plan["tenant_id"])
    await db.execute(
        text("""
            UPDATE custom_plans
            SET status = 'expired', updated_at = now()
            WHERE tenant_id = :tenant_id AND status = 'active'
        """),
        {"tenant_id": tenant_id},
    )
    await db.execute(
        text("""
            UPDATE custom_plans
            SET status = 'active', activated_at = now(), activated_by = :actor_id,
                payment_reference = :payment_reference, valid_until = :valid_until,
                updated_at = now()
            WHERE id = :plan_id
        """),
        {
            "plan_id": str(custom_plan_id),
            "actor_id": str(user.id),
            "payment_reference": body.payment_reference.strip(),
            "valid_until": valid_until,
        },
    )
    await log_audit(
        db,
        tenant_id=custom_plan["tenant_id"],
        actor_user_id=user.id,
        action="custom_plan.activate_verified",
        resource_type="custom_plan",
        resource_id=str(custom_plan_id),
        metadata={"payment_reference": body.payment_reference.strip(), "valid_until": valid_until.isoformat()},
        ip_address=get_client_ip(request),
    )
    await notify_tenant_managers(
        db, custom_plan["tenant_id"],
        notification_type="custom_plan.activated", title="تم تفعيل باقتك المخصصة",
        message=f"تم تفعيل باقتك المخصصة «{custom_plan['name']}» وهي صالحة حتى {valid_until.date().isoformat()}.",
        link="/settings/billing",
    )
    owner = await _tenant_owner_contact(db, custom_plan["tenant_id"])
    if owner:
        background_tasks.add_task(send_subscription_upgraded_email, owner["email"], custom_plan["name"], owner["full_name"])
    await db.commit()
    invalidate_subscription_state()
    return {"message": "Custom plan activated", "id": str(custom_plan_id), "valid_until": valid_until}


@router.post("/custom-plans/{custom_plan_id}/reject")
async def reject_custom_plan(
    custom_plan_id: UUID,
    body: RequestReview,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Send a submitted custom plan back to draft so the tenant can revise it."""
    plan_result = await db.execute(
        text("SELECT id, tenant_id, name, status FROM custom_plans WHERE id = :plan_id FOR UPDATE"),
        {"plan_id": str(custom_plan_id)},
    )
    custom_plan = plan_result.mappings().first()
    if not custom_plan:
        raise HTTPException(status_code=404, detail="Custom plan not found")
    if custom_plan["status"] != "pending_review":
        raise HTTPException(status_code=409, detail="Custom plan is not awaiting review")

    await db.execute(
        text("""
            UPDATE custom_plans
            SET status = 'draft', requested_period = NULL, request_notes = NULL, updated_at = now()
            WHERE id = :plan_id
        """),
        {"plan_id": str(custom_plan_id)},
    )
    await log_audit(
        db,
        tenant_id=custom_plan["tenant_id"],
        actor_user_id=user.id,
        action="custom_plan.rejected",
        resource_type="custom_plan",
        resource_id=str(custom_plan_id),
        metadata={"note": body.note},
        ip_address=get_client_ip(request),
    )
    await notify_tenant_managers(
        db, custom_plan["tenant_id"],
        notification_type="custom_plan.rejected", title="لم تتم الموافقة على باقتك المخصصة",
        message=body.note or f"لم تتم الموافقة على الباقة المخصصة «{custom_plan['name']}». يمكنك تعديلها وإعادة الإرسال.",
        link="/settings/billing",
    )
    owner = await _tenant_owner_contact(db, custom_plan["tenant_id"])
    if owner:
        background_tasks.add_task(
            send_subscription_request_rejected, owner["email"], owner["full_name"], custom_plan["name"], body.note or "",
        )
    await db.commit()
    return {"message": "Custom plan sent back to draft", "id": str(custom_plan_id)}


@router.get("/custom-plans/pending")
async def list_pending_custom_plans(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Custom plans a tenant has submitted for activation, oldest first."""
    rows = await db.execute(text("""
        SELECT cp.id, cp.tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
               cp.name, cp.total_price_monthly, cp.total_price_yearly,
               cp.requested_period, cp.request_notes, cp.request_phone, cp.final_limits, cp.created_at
        FROM custom_plans cp
        JOIN tenants t ON t.id = cp.tenant_id
        WHERE cp.status = 'pending_review'
        ORDER BY cp.created_at ASC
    """))
    return [dict(r) for r in rows.mappings().all()]


# ══════════════════════════════════════════════════
# SUBSCRIPTION REQUESTS (manual approval — Link Gateway disabled)
# ══════════════════════════════════════════════════

class PaymentInstructions(BaseModel):
    """Shown to workspaces next to every plan/renewal request."""

    value: str = Field(default="", max_length=2000)


@router.get("/payment-instructions")
async def get_payment_instructions(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    row = (await db.execute(text(
        "SELECT value, updated_at FROM platform_settings WHERE key = 'payment_instructions'"
    ))).mappings().first()
    return {"value": row["value"] if row else "", "updated_at": row["updated_at"] if row else None}


@router.put("/payment-instructions")
async def set_payment_instructions(
    body: PaymentInstructions,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    value = body.value.strip()
    await db.execute(text("""
        INSERT INTO platform_settings (key, value, updated_by, updated_at)
        VALUES ('payment_instructions', :v, :uid, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()
    """), {"v": value, "uid": str(user.id)})
    await log_audit(
        db, tenant_id=None, actor_user_id=user.id,
        action="platform.payment_instructions.update", resource_type="platform_setting",
        resource_id="payment_instructions", metadata={"length": len(value)},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return {"value": value}


@router.get("/subscription-requests")
async def list_subscription_requests(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Standard-plan requests awaiting staff review, oldest first.

    Each row carries the tenant's currently running plan and a suggested end
    date: a renewal of the same plan extends from the current end (remaining days
    are kept); anything else starts today.
    """
    rows = await db.execute(text("""
        SELECT ps.id, ps.tenant_id, t.name AS tenant_name, t.slug AS tenant_slug,
               p.code AS plan_code, p.name AS plan_name,
               p.price_monthly, p.price_yearly,
               ps.metadata, ps.created_at,
               cur.current_period_end, cp.code AS current_plan_code, cp.name AS current_plan_name
        FROM pending_subscriptions ps
        JOIN tenants t ON t.id = ps.tenant_id
        JOIN plans p ON p.id = ps.plan_id
        LEFT JOIN LATERAL (
            SELECT s.plan_id, s.current_period_end
            FROM subscriptions s
            WHERE s.tenant_id = ps.tenant_id AND s.status IN ('active', 'trialing')
            ORDER BY s.created_at DESC LIMIT 1
        ) cur ON true
        LEFT JOIN plans cp ON cp.id = cur.plan_id
        WHERE ps.provider = 'manual'
        ORDER BY ps.created_at ASC
    """))
    now = datetime.now(timezone.utc)
    out = []
    for r in rows.mappings().all():
        item = dict(r)
        same = item.get("current_plan_code") == item["plan_code"]
        period = (item.get("metadata") or {}).get("period", "monthly")
        end = item.get("current_period_end")
        item["is_renewal"] = bool(same and end and end > now)
        item["days_left"] = days_left(end, now)
        item["suggested_valid_until"] = renewal_valid_until(end, period, same_plan=same, now=now).isoformat()
        out.append(item)
    return out


@router.post("/subscription-requests/{pending_id}/approve")
async def approve_subscription_request(
    pending_id: UUID,
    body: SubscriptionRequestApproval,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Activate a requested standard plan after verifying payment out of band.

    Mirrors /custom-plans/{id}/activate: staff-only, auditable, and always has
    a defined end date. The pending row is removed once the real subscription
    is created, exactly like a successful Link confirmation would.
    """
    valid_until = body.valid_until
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="valid_until must be in the future")

    pending = (await db.execute(text("""
        SELECT ps.id, ps.tenant_id, ps.plan_id, ps.metadata, p.code AS plan_code, p.name AS plan_name
        FROM pending_subscriptions ps
        JOIN plans p ON p.id = ps.plan_id
        WHERE ps.id = :id AND ps.provider = 'manual'
        FOR UPDATE
    """), {"id": str(pending_id)})).mappings().first()
    if not pending:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    tenant_id = pending["tenant_id"]
    running = (await db.execute(text("""
        SELECT plan_id, current_period_end FROM subscriptions
        WHERE tenant_id = :tid AND status IN ('active', 'trialing')
        ORDER BY created_at DESC LIMIT 1
        FOR UPDATE
    """), {"tid": str(tenant_id)})).mappings().first()
    same_plan = bool(running and str(running["plan_id"]) == str(pending["plan_id"]))
    previous_end = running["current_period_end"] if running else None
    # Renewing the plan that is still running must extend it, never cut paid days.
    check_same_plan_extension(previous_end, valid_until, same_plan=same_plan)
    is_renewal = bool(same_plan and previous_end and previous_end > datetime.now(timezone.utc))

    await db.execute(
        text("UPDATE subscriptions SET status = 'canceled' WHERE tenant_id = :tid AND status IN ('active', 'trialing')"),
        {"tid": str(tenant_id)},
    )
    await db.execute(
        text("""
            INSERT INTO subscriptions
              (tenant_id, plan_id, provider, provider_customer_id, provider_subscription_id,
               status, current_period_start, current_period_end)
            VALUES (:tid, :pid, 'manual', 'staff_verified', :ref, 'active', now(), :valid_until)
        """),
        {
            "tid": str(tenant_id), "pid": str(pending["plan_id"]),
            "ref": body.payment_reference.strip(), "valid_until": valid_until,
        },
    )
    await sync_plan_cache(db, tenant_id, pending["plan_code"])
    await db.execute(text("DELETE FROM pending_subscriptions WHERE id = :id"), {"id": str(pending_id)})
    await log_audit(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="subscription.activated_manual",
        resource_type="subscription",
        resource_id=str(tenant_id),
        metadata={
            "plan_code": pending["plan_code"], "payment_reference": body.payment_reference.strip(),
            "valid_until": valid_until.isoformat(),
            "renewal": is_renewal,
            "previous_period_end": previous_end.isoformat() if previous_end else None,
        },
        ip_address=get_client_ip(request),
    )
    until = valid_until.date().isoformat()
    await notify_tenant_managers(
        db, tenant_id,
        notification_type="subscription.renewed" if is_renewal else "subscription.activated",
        title="تم تجديد اشتراكك" if is_renewal else "تم تفعيل باقتك",
        message=(
            f"تم تجديد باقة «{pending['plan_name']}» وهي صالحة الآن حتى {until}."
            if is_renewal else
            f"تم تفعيل باقة «{pending['plan_name']}» وهي صالحة حتى {until}."
        ),
        link="/settings/billing",
    )
    owner = await _tenant_owner_contact(db, tenant_id)
    if owner:
        if is_renewal:
            background_tasks.add_task(send_subscription_renewed_email, owner["email"], pending["plan_name"], until, owner["full_name"])
        else:
            background_tasks.add_task(send_subscription_upgraded_email, owner["email"], pending["plan_name"], owner["full_name"])
    await db.commit()
    invalidate_subscription_state()
    return {
        "message": "Subscription renewed" if is_renewal else "Subscription activated",
        "tenant_id": str(tenant_id), "valid_until": valid_until, "renewal": is_renewal,
    }


@router.post("/subscription-requests/{pending_id}/reject")
async def reject_subscription_request(
    pending_id: UUID,
    body: RequestReview,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Decline a standard-plan request. The tenant may submit a new one."""
    pending = (await db.execute(text("""
        SELECT ps.id, ps.tenant_id, p.name AS plan_name
        FROM pending_subscriptions ps
        JOIN plans p ON p.id = ps.plan_id
        WHERE ps.id = :id AND ps.provider = 'manual'
        FOR UPDATE
    """), {"id": str(pending_id)})).mappings().first()
    if not pending:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    await db.execute(text("DELETE FROM pending_subscriptions WHERE id = :id"), {"id": str(pending_id)})
    await log_audit(
        db,
        tenant_id=pending["tenant_id"],
        actor_user_id=user.id,
        action="subscription.rejected_manual",
        resource_type="pending_subscription",
        resource_id=str(pending_id),
        metadata={"note": body.note, "plan_name": pending["plan_name"]},
        ip_address=get_client_ip(request),
    )
    await notify_tenant_managers(
        db, pending["tenant_id"],
        notification_type="subscription.rejected", title="لم تتم الموافقة على طلب الباقة",
        message=body.note or f"لم تتم الموافقة على طلب باقة «{pending['plan_name']}».",
        link="/settings/billing",
    )
    owner = await _tenant_owner_contact(db, pending["tenant_id"])
    if owner:
        background_tasks.add_task(
            send_subscription_request_rejected, owner["email"], owner["full_name"], pending["plan_name"], body.note or "",
        )
    await db.commit()
    return {"message": "Subscription request rejected", "id": str(pending_id)}


@router.get("/stats")
async def platform_stats(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Get platform-wide statistics. Staff only."""
    result = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM tenants) AS total_tenants,
            (SELECT COUNT(*) FROM tenants WHERE status = 'active') AS active_tenants,
            (SELECT COUNT(*) FROM tenants WHERE status = 'trial') AS trial_tenants,
            (SELECT COUNT(*) FROM tenants WHERE status = 'suspended') AS suspended_tenants,
            (SELECT COUNT(*) FROM profiles) AS total_users,
            (SELECT COUNT(*) FROM memberships WHERE status = 'active') AS total_memberships,
            (SELECT COUNT(*) FROM subscriptions WHERE status = 'active') AS active_subscriptions
    """))
    row = result.mappings().first()
    return dict(row)


# ── Update Plan, Limits, and Addons ──

@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: UUID,
    body: PlanUpdate,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Update general plan details. Staff only."""
    updates = []
    params = {"pid": str(plan_id)}
    
    for field, val in body.dict(exclude_unset=True).items():
        updates.append(f"{field} = :{field}")
        params[field] = val
        
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لتحديثها")
        
    query = f"UPDATE plans SET {', '.join(updates)}, updated_at = now() WHERE id = :pid"
    await db.execute(text(query), params)
    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=user.id,
        action="plan.update",
        resource_type="plan",
        resource_id=str(plan_id),
        metadata={"updated_fields": list(body.dict(exclude_unset=True).keys())}
    )
    await db.commit()
    return {"message": "تم تحديث الباقة بنجاح"}


@router.get("/plans/{plan_id}/limits")
async def get_plan_limits(
    plan_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Get all limits for a specific plan. Staff only."""
    result = await db.execute(
        text("SELECT key, value, period FROM plan_limits WHERE plan_id = :pid"),
        {"pid": str(plan_id)}
    )
    return [dict(r) for r in result.mappings().all()]


@router.put("/plans/{plan_id}/limits")
async def update_plan_limits(
    plan_id: UUID,
    limits: list[PlanLimitItem],
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Update all limits for a specific plan. Staff only."""
    keys = [item.key.strip() for item in limits]
    if not keys or any(not key for key in keys):
        raise HTTPException(status_code=422, detail="At least one named plan limit is required")
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Each plan-limit key may appear only once")
    if any(item.value < -1 for item in limits):
        raise HTTPException(status_code=422, detail="Plan limits must be -1 (unlimited) or a non-negative value")

    # Delete existing limits
    await db.execute(text("DELETE FROM plan_limits WHERE plan_id = :pid"), {"pid": str(plan_id)})
    
    # Insert new limits
    for limit in limits:
        await db.execute(
            text("INSERT INTO plan_limits (plan_id, key, value, period) VALUES (:pid, :key, :val, :per)"),
            {"pid": str(plan_id), "key": limit.key, "val": limit.value, "per": limit.period}
        )
    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=user.id,
        action="plan.limits_update",
        resource_type="plan",
        resource_id=str(plan_id),
        metadata={"limits_count": len(limits)}
    )
    await db.commit()
    return {"message": "تم تحديث حدود الباقة بنجاح"}


@router.patch("/addons/{addon_id}")
async def update_addon(
    addon_id: UUID,
    body: AddonUpdate,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Update plan addon details. Staff only."""
    updates = []
    params = {"aid": str(addon_id)}
    
    for field, val in body.dict(exclude_unset=True).items():
        updates.append(f"{field} = :{field}")
        params[field] = val
        
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد بيانات لتحديثها")
        
    query = f"UPDATE plan_addons SET {', '.join(updates)} WHERE id = :aid"
    await db.execute(text(query), params)
    await log_audit(
        db,
        tenant_id=None,
        actor_user_id=user.id,
        action="addon.update",
        resource_type="addon",
        resource_id=str(addon_id),
        metadata={"updated_fields": list(body.dict(exclude_unset=True).keys())}
    )
    await db.commit()
    return {"message": "تم تحديث الميزة الإضافية بنجاح"}


# ══════════════════════════════════════════════════
# ROLES & PERMISSIONS (Platform staff only)
# ══════════════════════════════════════════════════

async def _tenant_exists(db: AsyncSession, tenant_id: UUID) -> None:
    row = await db.execute(
        text("SELECT 1 FROM tenants WHERE id = :tid"),
        {"tid": str(tenant_id)},
    )
    if not row.first():
        raise HTTPException(status_code=404, detail="المؤسسة غير موجودة")


@router.get("/permissions", response_model=list[PermissionRead])
async def platform_list_permissions(
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List all system permissions. Platform staff only."""
    result = await db.execute(
        text("SELECT key, description FROM permissions ORDER BY key")
    )
    return [PermissionRead(**dict(r)) for r in result.mappings().all()]


@router.get("/tenants/{tenant_id}/roles", response_model=list[RoleRead])
async def platform_list_tenant_roles(
    tenant_id: UUID,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List roles and permissions for a tenant. Platform staff only."""
    await _tenant_exists(db, tenant_id)
    result = await db.execute(
        text("""
            SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                   r.created_at::text,
                   ARRAY(
                       SELECT rp.permission_key FROM role_permissions rp WHERE rp.role_id = r.id
                   ) AS permissions
            FROM roles r
            WHERE r.tenant_id = :tid
            ORDER BY r.is_system_role DESC, r.name
        """),
        {"tid": str(tenant_id)},
    )
    return [RoleRead(**dict(r)) for r in result.mappings().all()]


@router.post("/tenants/{tenant_id}/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def platform_create_role(
    tenant_id: UUID,
    body: RoleCreate,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Create a custom role for a tenant. Platform staff only."""
    await _tenant_exists(db, tenant_id)

    existing = await db.execute(
        text("SELECT 1 FROM roles WHERE tenant_id = :tid AND name = :name"),
        {"tid": str(tenant_id), "name": body.name},
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="يوجد دور بنفس الاسم")

    if body.permissions:
        valid = await db.execute(
            text("SELECT key FROM permissions WHERE key = ANY(:keys)"),
            {"keys": body.permissions},
        )
        valid_keys = {r[0] for r in valid.fetchall()}
        invalid = set(body.permissions) - valid_keys
        if invalid:
            raise HTTPException(status_code=400, detail=f"صلاحيات غير موجودة: {', '.join(invalid)}")

    result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, :name, :desc, false)
            RETURNING id, tenant_id, name, description, is_system_role, created_at::text
        """),
        {"tid": str(tenant_id), "name": body.name, "desc": body.description},
    )
    role = result.mappings().first()

    for pkey in body.permissions:
        await db.execute(
            text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:rid, :pkey)"),
            {"rid": str(role["id"]), "pkey": pkey},
        )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="platform.role.create", resource_type="role", resource_id=str(role["id"]),
        metadata={"name": body.name, "permissions": body.permissions},
        ip_address=get_client_ip(request),
    )
    await db.commit()
    return RoleRead(**dict(role), permissions=body.permissions)


@router.patch("/tenants/{tenant_id}/roles/{role_id}", response_model=RoleRead)
async def platform_update_role(
    tenant_id: UUID,
    role_id: UUID,
    body: RoleUpdate,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Update role permissions for a tenant. Platform staff only."""
    await _tenant_exists(db, tenant_id)

    existing = await db.execute(
        text("SELECT id, is_system_role FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": str(role_id), "tid": str(tenant_id)},
    )
    role_row = existing.mappings().first()
    if not role_row:
        raise HTTPException(status_code=404, detail="الدور غير موجود")
    is_system = role_row["is_system_role"]

    updates = body.model_dump(exclude_unset=True, exclude={"permissions"})
    if updates:
        if is_system:
            raise HTTPException(status_code=403, detail="لا يمكن تعديل اسم أو وصف الأدوار النظامية")
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["rid"] = str(role_id)
        await db.execute(text(f"UPDATE roles SET {set_clauses} WHERE id = :rid"), updates)

    if body.permissions is not None:
        if body.permissions:
            valid = await db.execute(
                text("SELECT key FROM permissions WHERE key = ANY(:keys)"),
                {"keys": body.permissions},
            )
            valid_keys = {r[0] for r in valid.fetchall()}
            invalid = set(body.permissions) - valid_keys
            if invalid:
                raise HTTPException(status_code=400, detail=f"صلاحيات غير موجودة: {', '.join(invalid)}")

        await db.execute(
            text("DELETE FROM role_permissions WHERE role_id = :rid"),
            {"rid": str(role_id)},
        )
        for pkey in body.permissions:
            await db.execute(
                text("INSERT INTO role_permissions (role_id, permission_key) VALUES (:rid, :pkey)"),
                {"rid": str(role_id), "pkey": pkey},
            )

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="platform.role.update", resource_type="role", resource_id=str(role_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()

    result = await db.execute(
        text("""
            SELECT r.id, r.tenant_id, r.name, r.description, r.is_system_role,
                   r.created_at::text,
                   ARRAY(SELECT rp.permission_key FROM role_permissions rp WHERE rp.role_id = r.id) AS permissions
            FROM roles r WHERE r.id = :rid
        """),
        {"rid": str(role_id)},
    )
    return RoleRead(**dict(result.mappings().first()))


@router.delete("/tenants/{tenant_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def platform_delete_role(
    tenant_id: UUID,
    role_id: UUID,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Delete a custom role. Platform staff only."""
    await _tenant_exists(db, tenant_id)

    existing = await db.execute(
        text("SELECT id, is_system_role FROM roles WHERE id = :rid AND tenant_id = :tid"),
        {"rid": str(role_id), "tid": str(tenant_id)},
    )
    role_row = existing.mappings().first()
    if not role_row:
        raise HTTPException(status_code=404, detail="الدور غير موجود")
    if role_row["is_system_role"]:
        raise HTTPException(status_code=403, detail="لا يمكن حذف الأدوار النظامية")

    assigned = await db.execute(
        text("SELECT 1 FROM membership_roles WHERE role_id = :rid LIMIT 1"),
        {"rid": str(role_id)},
    )
    if assigned.first():
        raise HTTPException(status_code=409, detail="لا يمكن حذف دور مُسند لأعضاء. قم بإزالة الدور من الأعضاء أولاً.")

    await db.execute(text("DELETE FROM roles WHERE id = :rid"), {"rid": str(role_id)})

    await log_audit(
        db, tenant_id=tenant_id, actor_user_id=user.id,
        action="platform.role.delete", resource_type="role", resource_id=str(role_id),
        ip_address=get_client_ip(request),
    )
    await db.commit()


# ══════════════════════════════════════════════════
# TEAM CREATION REQUESTS — platform approval
# ══════════════════════════════════════════════════

@router.get("/team-requests", response_model=list[TeamRequestRead])
async def platform_list_team_requests(
    status_filter: Optional[str] = Query("pending", alias="status"),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List team-creation requests across all tenants. Staff only."""
    query = """
        SELECT tr.*, p.full_name AS requester_name, tn.name AS tenant_name
        FROM team_requests tr
        JOIN profiles p ON p.id = tr.requested_by
        JOIN tenants tn ON tn.id = tr.tenant_id
    """
    params = {}
    if status_filter and status_filter != "all":
        query += " WHERE tr.status = :st"
        params["st"] = status_filter
    query += " ORDER BY tr.created_at DESC"

    result = await db.execute(text(query), params)
    return [TeamRequestRead(**dict(r)) for r in result.mappings().all()]


@router.post("/team-requests/{request_id}/approve", response_model=TeamRequestRead)
async def platform_approve_team_request(
    request_id: UUID,
    body: TeamRequestReview,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    raise HTTPException(410, "تم إيقاف طلبات الفرق الداخلية؛ الاعتماد يتم من طلبات فرق التنظيم")


@router.post("/team-requests/{request_id}/reject", response_model=TeamRequestRead)
async def platform_reject_team_request(
    request_id: UUID,
    body: TeamRequestReview,
    request: Request,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    raise HTTPException(410, "تم إيقاف طلبات الفرق الداخلية؛ الاعتماد يتم من طلبات فرق التنظيم")


# ══════════════════════════════════════════════════
# ORGANIZER-TEAM REGISTRATION REQUESTS — platform approval
# ══════════════════════════════════════════════════

class OrgRequestRead(BaseModel):
    id: UUID
    status: str
    full_name: str
    email: str
    phone: Optional[str] = None
    org_name: str
    org_type: Optional[str] = None
    description: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    website: Optional[str] = None
    contact_handle: Optional[str] = None
    expected_events_per_month: Optional[int] = None
    expected_attendees: Optional[int] = None
    requested_plan_code: Optional[str] = None
    proof_url: Optional[str] = None
    documents_url: Optional[str] = None
    notes: Optional[str] = None
    review_note: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_tenant_id: Optional[UUID] = None
    created_at: str


class OrgRequestReview(BaseModel):
    note: Optional[str] = None


def _org_request_row(r) -> OrgRequestRead:
    d = dict(r)
    for k in ("reviewed_at", "created_at"):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return OrgRequestRead(**{k: d.get(k) for k in OrgRequestRead.model_fields})


def _auth_response_user_id(response) -> str:
    user = response.get("user") if isinstance(response, dict) else getattr(response, "user", None)
    if isinstance(user, dict):
        return str(user.get("id") or "")
    return str(getattr(user, "id", "") or "")


async def _sign_org_request_documents(row: OrgRequestRead) -> OrgRequestRead:
    """Replace private Storage references with short-lived staff-only links."""
    storage = get_supabase_admin().storage.from_("invitations")
    legacy_marker = "/invitations/"

    async def sign(value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        if value.startswith("public-org-requests/"):
            object_path = value
        elif legacy_marker in value:
            object_path = value.split(legacy_marker, 1)[1].split("?", 1)[0]
        else:
            return value
        try:
            result = await asyncio.to_thread(storage.create_signed_url, object_path, 900)
            return result.get("signedURL") or result.get("signedUrl") or value
        except Exception as exc:
            logger.warning("Failed to sign organizer document %s: %s", object_path, exc)
            return value

    row.proof_url, row.documents_url = await asyncio.gather(
        sign(row.proof_url), sign(row.documents_url)
    )
    return row


@router.get("/org-requests", response_model=list[OrgRequestRead])
async def platform_list_org_requests(
    status_filter: Optional[str] = Query("pending", alias="status"),
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """List organizer-team registration requests. Staff only."""
    query = "SELECT * FROM organization_requests"
    params = {}
    if status_filter and status_filter != "all":
        query += " WHERE status = :st"
        params["st"] = status_filter
    query += " ORDER BY created_at DESC"
    result = await db.execute(text(query), params)
    rows = [_org_request_row(r) for r in result.mappings().all()]
    return await asyncio.gather(*(_sign_org_request_documents(row) for row in rows))


@router.post("/org-requests/{request_id}/approve", response_model=OrgRequestRead)
async def platform_approve_org_request(
    request_id: UUID,
    body: OrgRequestReview,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Approve an org request, create its identity, then provision its workspace."""
    # Serialize review actions so two staff members cannot provision the same
    # request concurrently.
    res = await db.execute(
        text("SELECT * FROM organization_requests WHERE id = :id FOR UPDATE"),
        {"id": str(request_id)},
    )
    req = res.mappings().first()
    if not req:
        raise HTTPException(404, "الطلب غير موجود")
    if req["status"] != "pending":
        raise HTTPException(409, "تمت معالجة هذا الطلب مسبقاً")

    email = req["email"].lower().strip()
    new_user_id = str(req["created_user_id"]) if req["created_user_id"] else None
    created_auth_user = False
    admin = get_supabase_admin()

    try:
        if new_user_id:
            await asyncio.to_thread(
                admin.auth.admin.update_user_by_id,
                new_user_id,
                {"email_confirm": True},
            )
        else:
            encrypted_password = req["password_encrypted"]
            if not encrypted_password:
                raise ValueError("Pending request has no encrypted password")
            password = decrypt_secret(str(encrypted_password))
            created = await asyncio.to_thread(
                admin.auth.admin.create_user,
                {
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": req["full_name"] or ""},
                },
            )
            new_user_id = _auth_response_user_id(created)
            if not new_user_id:
                raise RuntimeError("Supabase did not return a created user id")
            created_auth_user = True
    except Exception as auth_err:
        logger.error("Failed to prepare identity for org request %s: %s", request_id, auth_err)
        raise HTTPException(500, "فشل تجهيز حساب المستخدم في بوابة الهوية")

    # ── Create tenant + membership + subscription + provisioning + profile ──
    try:
        org_name = req["org_name"]
        base_slug = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")
        if len(base_slug) < 3:
            base_slug = f"org-{base_slug}"
        slug = f"{base_slug[:40]}-{secrets.token_hex(3)}"
        plan_code = req["requested_plan_code"] or "starter"

        tenant_result = await db.execute(
            text("""
                INSERT INTO tenants (slug, name, created_by, workspace_type, metadata)
                VALUES (:slug, :name, :created_by, 'organizer', '{}'::jsonb)
                RETURNING id, slug, name, status, plan, created_at
            """),
            {"slug": slug, "name": org_name, "created_by": new_user_id},
        )
        tenant = tenant_result.mappings().first()
        tenant_id = str(tenant["id"])

        await db.execute(
            text("""
                INSERT INTO memberships (tenant_id, user_id, role, status)
                VALUES (:tid, :uid, 'owner', 'active')
            """),
            {"tid": tenant_id, "uid": new_user_id},
        )

        await db.execute(
            text("""
                INSERT INTO subscriptions (tenant_id, plan_id, status,
                    current_period_start, current_period_end, trial_ends_at)
                VALUES (
                    :tid,
                    COALESCE((SELECT id FROM plans WHERE code = :plan_code),
                             (SELECT id FROM plans WHERE code = 'starter')),
                    'active', now(), now() + INTERVAL '30 days',
                    now() + INTERVAL '14 days'
                )
            """),
            {"tid": tenant_id, "plan_code": plan_code},
        )

        await provision_tenant_manual(db, tenant["id"], UUID(new_user_id))
        institution_tenant_id = await ensure_linked_institution_workspace(
            db,
            tenant["id"],
            UUID(new_user_id),
            org_name,
        )

        await db.execute(
            text("""
                INSERT INTO profiles (id, full_name, avatar_url)
                VALUES (:uid, :name, '')
                ON CONFLICT (id) DO NOTHING
            """),
            {"uid": new_user_id, "name": req["full_name"] or ""},
        )

        # Mark request approved
        updated = await db.execute(
            text("""
                UPDATE organization_requests
                SET status = 'approved', reviewed_by = :rev, review_note = :note,
                    reviewed_at = now(), created_tenant_id = :tid,
                    institution_tenant_id = :institution_tid, created_user_id = :uid,
                    password_encrypted = NULL
                WHERE id = :id
                RETURNING *
            """),
            {"rev": str(user.id), "note": body.note, "tid": tenant_id,
             "institution_tid": str(institution_tenant_id),
             "uid": new_user_id, "id": str(request_id)},
        )
        row = updated.mappings().first()

        await ensure_team_manager_role(db, tenant["id"], UUID(new_user_id))

        await log_audit(db, tenant_id=tenant["id"], actor_user_id=user.id,
                        action="platform.org_request.approve", resource_type="organization_request",
                        resource_id=str(request_id),
                        ip_address=get_client_ip(request))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("Provisioning failed for approved org request %s: %s", request_id, e)
        try:
            if created_auth_user:
                await asyncio.to_thread(admin.auth.admin.delete_user, new_user_id)
            elif new_user_id:
                await asyncio.to_thread(
                    admin.auth.admin.update_user_by_id,
                    new_user_id,
                    {"email_confirm": False},
                )
        except Exception as cleanup_err:
            logger.error("Failed to compensate auth state for org request %s: %s", request_id, cleanup_err)
        raise HTTPException(500, "فشل تجهيز المؤسسة. لم تتم الموافقة. حاول مرة أخرى.")

    background_tasks.add_task(send_org_request_approved, email, req["full_name"], org_name)
    return _org_request_row(row)


@router.post("/org-requests/{request_id}/reject", response_model=OrgRequestRead)
async def platform_reject_org_request(
    request_id: UUID,
    body: OrgRequestReview,
    request: Request,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_privileged_db),
):
    """Reject an org request and remove any legacy pre-created Auth user."""
    res = await db.execute(
        text("SELECT * FROM organization_requests WHERE id = :id FOR UPDATE"),
        {"id": str(request_id)},
    )
    req = res.mappings().first()
    if not req:
        raise HTTPException(404, "الطلب غير موجود")
    if req["status"] != "pending":
        raise HTTPException(409, "تمت معالجة هذا الطلب مسبقاً")

    created_user_id = req["created_user_id"]

    updated = await db.execute(
        text("""
            UPDATE organization_requests
            SET status = 'rejected', reviewed_by = :rev, review_note = :note,
                reviewed_at = now(), password_encrypted = NULL
            WHERE id = :id
            RETURNING *
        """),
        {"rev": str(user.id), "note": body.note, "id": str(request_id)},
    )
    row = updated.mappings().first()

    await log_audit(db, tenant_id=None, actor_user_id=user.id,
                    action="platform.org_request.reject", resource_type="organization_request",
                    resource_id=str(request_id),
                    ip_address=get_client_ip(request))
    await db.commit()

    if created_user_id:
        try:
            admin = get_supabase_admin()
            await asyncio.to_thread(admin.auth.admin.delete_user, str(created_user_id))
        except Exception as delete_err:
            logger.warning(
                "Rejected request %s, but could not delete legacy Auth user %s: %s",
                request_id,
                created_user_id,
                delete_err,
            )

    background_tasks.add_task(
        send_org_request_rejected, req["email"], req["full_name"], req["org_name"], body.note or "",
    )
    return _org_request_row(row)
