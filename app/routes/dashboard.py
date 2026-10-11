"""
Dashboard Analytics — Real-time stats for tenant dashboard.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user, get_tenant_id_from_header, CurrentUser
from app.services.permission_service import require_permission
from app.services.entitlement_service import resolve_billing_tenant, resolve_plan

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = logging.getLogger(__name__)


async def safe_query(db: AsyncSession, sql: str, params: dict):
    """Run a query safely, returning None on error (e.g. table not found)."""
    try:
        result = await db.execute(text(sql), params)
        return result
    except Exception as exc:
        await db.rollback()
        logger.warning("Dashboard query failed: %s", exc)
        return None


@router.get("/analytics")
async def get_dashboard_analytics(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Comprehensive tenant dashboard analytics.
    Each section is queried separately for resilience.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "reports.view")

    analytics = {}
    # An institution is the management overview for its linked organizer.
    # Include events operated by that team without giving the institution
    # write access to the client event itself.
    p = {"tid": tenant_id, "uid": str(user.id), "linked_organizer_id": None}

    # ── Tenant info ──
    r = await safe_query(db, """
        SELECT name, slug, status::text, plan, created_at::text, expires_at::text
        FROM tenants WHERE id = :tid
    """, p)
    if r:
        row = r.mappings().first()
        analytics["tenant"] = dict(row) if row else None
    else:
        analytics["tenant"] = None

    r = await safe_query(db, """
        SELECT wl.organizer_tenant_id::text AS tenant_id, t.name
        FROM workspace_links wl
        JOIN tenants t ON t.id = wl.organizer_tenant_id
        WHERE wl.institution_tenant_id = :tid AND wl.status = 'active'
        LIMIT 1
    """, p)
    linked_row = r.mappings().first() if r else None
    linked_organizer = dict(linked_row) if linked_row else None
    if linked_organizer:
        p["linked_organizer_id"] = linked_organizer["tenant_id"]
    analytics["linked_organizer"] = linked_organizer

    # ── Member stats ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) FILTER (WHERE status = 'active') AS active_members,
            COUNT(*) FILTER (WHERE status = 'invited') AS pending_invites,
            COUNT(*) FILTER (WHERE status = 'disabled') AS disabled_members,
            COUNT(*) AS total_members,
            COUNT(*) FILTER (WHERE role = 'owner') AS owners,
            COUNT(*) FILTER (WHERE role = 'admin') AS admins,
            COUNT(*) FILTER (WHERE role = 'member') AS members,
            COUNT(*) FILTER (WHERE role = 'viewer') AS viewers,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS new_members_7d,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_members_30d
        FROM memberships WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["members"] = dict(r.mappings().first())
    else:
        analytics["members"] = {"total_members": 0, "active_members": 0, "pending_invites": 0,
                                "disabled_members": 0, "owners": 0, "admins": 0, "members": 0,
                                "viewers": 0, "new_members_7d": 0, "new_members_30d": 0}

    # ── Events ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_events,
            COUNT(*) FILTER (WHERE status = 'active' OR status = 'published') AS active_events,
            COUNT(*) FILTER (WHERE status = 'draft') AS draft_events,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_events,
            COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_events,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS new_events_7d,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_events_30d,
            MAX(created_at)::text AS last_event_created
        FROM events e
        WHERE e.tenant_id = :tid
           OR (
                CAST(:linked_organizer_id AS uuid) IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM event_operations o
                    WHERE o.event_id = e.id
                      AND o.provider_tenant_id = CAST(:linked_organizer_id AS uuid)
                      AND o.status <> 'cancelled'
                )
           )
    """, p)
    if r:
        analytics["events"] = dict(r.mappings().first())
    else:
        analytics["events"] = {"total_events": 0, "active_events": 0, "draft_events": 0,
                               "completed_events": 0, "cancelled_events": 0, "new_events_7d": 0,
                               "new_events_30d": 0, "last_event_created": None}

    # ── Guests ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_guests,
            COUNT(*) FILTER (WHERE g.created_at >= CURRENT_DATE - INTERVAL '7 days') AS new_guests_7d,
            COUNT(*) FILTER (WHERE g.created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_guests_30d,
            COUNT(*) FILTER (WHERE i.rsvp_status::text = 'accepted') AS confirmed_guests,
            COUNT(*) FILTER (WHERE i.rsvp_status::text = 'declined') AS declined_guests,
            COUNT(*) FILTER (WHERE COALESCE(i.rsvp_status::text, 'pending') IN ('pending', 'maybe')) AS pending_guests,
            COUNT(*) FILTER (WHERE i.checked_in_at IS NOT NULL) AS checked_in_guests
        FROM guests g
        LEFT JOIN LATERAL (
            SELECT rsvp_status, checked_in_at
            FROM invitations gi
            WHERE gi.guest_id = g.id
              AND gi.status::text NOT IN ('revoked', 'expired')
            ORDER BY gi.created_at DESC
            LIMIT 1
        ) i ON TRUE
        WHERE g.tenant_id = :tid
           OR (
                CAST(:linked_organizer_id AS uuid) IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM invitations gi2
                    JOIN event_operations o ON o.event_id = gi2.event_id
                    WHERE gi2.guest_id = g.id
                      AND o.provider_tenant_id = CAST(:linked_organizer_id AS uuid)
                      AND o.status <> 'cancelled'
                )
           )
    """, p)
    if r:
        analytics["guests"] = dict(r.mappings().first())
    else:
        analytics["guests"] = {"total_guests": 0, "confirmed_guests": 0, "declined_guests": 0,
                               "pending_guests": 0, "checked_in_guests": 0, "new_guests_7d": 0,
                               "new_guests_30d": 0}

    # ── Digital Invitations ──
    r = await safe_query(db, """
        WITH scoped AS (
            SELECT i.*
            FROM invitations i
            WHERE (i.tenant_id = :tid OR (
                    CAST(:linked_organizer_id AS uuid) IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM event_operations o
                        WHERE o.event_id = i.event_id
                          AND o.provider_tenant_id = CAST(:linked_organizer_id AS uuid)
                          AND o.status <> 'cancelled'
                    )
                ))
              AND i.status::text NOT IN ('revoked', 'expired')
              AND COALESCE(i.metadata->>'generation_deleted', 'false') <> 'true'
        ), delivery AS (
            SELECT d.invitation_id,
                   BOOL_OR(d.sent_at IS NOT NULL OR d.status IN ('sent','delivered','opened')) AS sent,
                   BOOL_OR(d.delivered_at IS NOT NULL OR d.status IN ('delivered','opened')) AS delivered,
                   BOOL_OR(d.opened_at IS NOT NULL OR d.status = 'opened') AS opened,
                   BOOL_OR(d.status IN ('failed','bounced')) AS failed
            FROM invitation_deliveries d
            JOIN scoped s ON s.id = d.invitation_id
            GROUP BY d.invitation_id
        )
        SELECT
            COUNT(*) AS total_invitations,
            COUNT(*) FILTER (WHERE d.sent OR s.status::text IN ('sent','viewed','accepted','declined','checked_in')) AS sent_invitations,
            COUNT(*) FILTER (WHERE d.delivered) AS delivered_invitations,
            COUNT(*) FILTER (WHERE d.opened OR s.status::text = 'viewed') AS opened_invitations,
            COUNT(*) FILTER (WHERE d.failed) AS failed_invitations,
            COUNT(*) FILTER (WHERE s.rsvp_status::text = 'accepted') AS accepted_invitations,
            COUNT(*) FILTER (WHERE s.rsvp_status::text = 'declined') AS declined_invitations,
            COUNT(*) FILTER (WHERE s.rsvp_status::text = 'maybe') AS maybe_invitations,
            COUNT(*) FILTER (WHERE COALESCE(s.rsvp_status::text, 'pending') = 'pending') AS pending_invitations,
            COUNT(*) FILTER (WHERE s.checked_in_at IS NOT NULL) AS checked_in_invitations,
            COALESCE(SUM(GREATEST(COALESCE(s.guest_count, 1), 1)), 0) AS invited_people,
            COALESCE(SUM(GREATEST(COALESCE(s.checkin_count, 0), 0)), 0) AS checked_in_people,
            COUNT(*) FILTER (WHERE s.created_at >= CURRENT_DATE - INTERVAL '7 days') AS new_invitations_7d,
            COUNT(*) FILTER (WHERE s.created_at >= CURRENT_DATE - INTERVAL '30 days') AS new_invitations_30d
        FROM scoped s
        LEFT JOIN delivery d ON d.invitation_id = s.id
    """, p)
    if r:
        analytics["invitations"] = dict(r.mappings().first())
    else:
        analytics["invitations"] = {"total_invitations": 0, "sent_invitations": 0,
                                    "delivered_invitations": 0, "opened_invitations": 0,
                                    "failed_invitations": 0, "accepted_invitations": 0,
                                    "declined_invitations": 0, "maybe_invitations": 0,
                                    "pending_invitations": 0, "checked_in_invitations": 0,
                                    "invited_people": 0, "checked_in_people": 0,
                                    "new_invitations_7d": 0, "new_invitations_30d": 0}

    # ── Real daily trends (zero-filled by PostgreSQL) ──
    r = await safe_query(db, """
        WITH days AS (
            SELECT generate_series(CURRENT_DATE - INTERVAL '29 days', CURRENT_DATE, INTERVAL '1 day')::date AS day
        ), scoped_events AS (
            SELECT e.id, e.created_at::date AS day
            FROM events e
            WHERE e.tenant_id = :tid OR (
                CAST(:linked_organizer_id AS uuid) IS NOT NULL AND EXISTS (
                    SELECT 1 FROM event_operations o WHERE o.event_id=e.id
                      AND o.provider_tenant_id=CAST(:linked_organizer_id AS uuid) AND o.status<>'cancelled'
                )
            )
        ), scoped_invitations AS (
            SELECT i.id, i.created_at::date AS day, i.checked_in_at::date AS checkin_day
            FROM invitations i JOIN scoped_events e ON e.id=i.event_id
            WHERE i.status::text NOT IN ('revoked','expired')
              AND COALESCE(i.metadata->>'generation_deleted','false')<>'true'
        )
        SELECT d.day::text,
               COUNT(DISTINCT e.id) AS events,
               COUNT(DISTINCT i.id) AS invitations,
               COUNT(DISTINCT ci.id) AS checkins
        FROM days d
        LEFT JOIN scoped_events e ON e.day=d.day
        LEFT JOIN scoped_invitations i ON i.day=d.day
        LEFT JOIN scoped_invitations ci ON ci.checkin_day=d.day
        GROUP BY d.day ORDER BY d.day
    """, p)
    analytics["daily_trend"] = [dict(row) for row in r.mappings().all()] if r else []

    # ── Distribution and operational quality ──
    r = await safe_query(db, """
        SELECT e.status::text AS status, COUNT(*) AS count
        FROM events e
        WHERE e.tenant_id=:tid OR (
            CAST(:linked_organizer_id AS uuid) IS NOT NULL AND EXISTS (
                SELECT 1 FROM event_operations o WHERE o.event_id=e.id
                  AND o.provider_tenant_id=CAST(:linked_organizer_id AS uuid) AND o.status<>'cancelled'
            )
        )
        GROUP BY e.status::text ORDER BY count DESC
    """, p)
    analytics["event_status_distribution"] = [dict(row) for row in r.mappings().all()] if r else []

    r = await safe_query(db, """
        WITH scoped_events AS (
            SELECT e.id FROM events e WHERE e.tenant_id=:tid OR (
                CAST(:linked_organizer_id AS uuid) IS NOT NULL AND EXISTS (
                    SELECT 1 FROM event_operations o WHERE o.event_id=e.id
                      AND o.provider_tenant_id=CAST(:linked_organizer_id AS uuid) AND o.status<>'cancelled'
                )
            )
        )
        SELECT COUNT(*) AS total_scans,
               COUNT(*) FILTER (WHERE c.result::text='success') AS successful_scans,
               COUNT(*) FILTER (WHERE c.result::text IN ('already_checked_in','duplicate')) AS duplicate_scans,
               COUNT(*) FILTER (WHERE c.result::text NOT IN ('success','already_checked_in','duplicate')) AS rejected_scans,
               COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE c.result::text='success') / NULLIF(COUNT(*),0), 1), 0) AS scan_success_rate,
               COUNT(*) FILTER (WHERE c.created_at >= CURRENT_DATE) AS scans_today,
               COUNT(*) FILTER (WHERE c.created_at >= CURRENT_DATE - INTERVAL '7 days') AS scans_7d
        FROM checkins c JOIN scoped_events e ON e.id=c.event_id
    """, p)
    analytics["checkin_quality"] = dict(r.mappings().first()) if r else {
        "total_scans": 0, "successful_scans": 0, "duplicate_scans": 0,
        "rejected_scans": 0, "scan_success_rate": 0, "scans_today": 0, "scans_7d": 0,
    }

    # ── Templates ──
    r = await safe_query(db, """
        SELECT COUNT(*) AS total_templates
        FROM invite_templates WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["templates"] = dict(r.mappings().first())
    else:
        analytics["templates"] = {"total_templates": 0}

    # ── Subscription ──
    # Linked institution/organizer workspaces share ONE commercial plan, held by
    # the billing tenant.  Reading the current workspace's own subscription row
    # showed "free" on the institution side after the organizer's plan was
    # approved (the institution has no subscription of its own).
    p["billing_tid"] = tenant_id
    billing_tenant_id = None
    try:
        billing_tenant_id = await resolve_billing_tenant(db, UUID(str(tenant_id)))
        p["billing_tid"] = str(billing_tenant_id)
    except Exception as exc:  # pragma: no cover - fall back to the workspace itself
        logger.warning("Dashboard could not resolve the billing tenant: %s", exc)
    analytics["billing"] = {
        "tenant_id": p["billing_tid"],
        "shared": p["billing_tid"] != str(tenant_id),
    }
    r = await safe_query(db, """
        SELECT
            s.status::text AS sub_status,
            p.name AS plan_name,
            p.code AS plan_code,
            p.price_monthly,
            s.current_period_start::text,
            s.current_period_end::text,
            s.trial_ends_at::text,
            s.cancel_at_period_end
        FROM subscriptions s
        JOIN plans p ON p.id = s.plan_id
        WHERE s.tenant_id = :billing_tid
        ORDER BY (s.status IN ('active', 'trialing')) DESC, s.created_at DESC
        LIMIT 1
    """, p)
    if r:
        row = r.mappings().first()
        analytics["subscription"] = dict(row) if row else None
    else:
        analytics["subscription"] = None

    # The effective plan (custom plan > valid subscription > fallback) is what
    # limits are enforced against; show exactly that, not tenants.plan.
    try:
        effective = await resolve_plan(db, UUID(str(tenant_id)))
        if analytics.get("tenant"):
            analytics["tenant"]["plan"] = effective["code"]
        sub = analytics.get("subscription")
        if sub is not None:
            sub["plan_code"] = effective["code"]
            sub["plan_name"] = effective["name"]
            sub["plan_source"] = effective.get("source")
    except Exception as exc:  # pragma: no cover
        logger.warning("Dashboard could not resolve the effective plan: %s", exc)

    # Display the same billing-scope counters as the enforcing service.
    from app.services.usage_service import get_current_usage
    counters = await get_current_usage(db, tenant_id)
    analytics["usage"] = [{"key": key, "value": value} for key, value in counters.items()]

    # ── Team invites ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_team_invites,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_team_invites,
            COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_team_invites,
            COUNT(*) FILTER (WHERE status = 'expired') AS expired_team_invites
        FROM invites WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["team_invites"] = dict(r.mappings().first())
    else:
        analytics["team_invites"] = {"total_team_invites": 0, "pending_team_invites": 0,
                                     "accepted_team_invites": 0, "expired_team_invites": 0}

    # ── Roles ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_roles,
            COUNT(*) FILTER (WHERE is_system_role = true) AS system_roles,
            COUNT(*) FILTER (WHERE is_system_role = false) AS custom_roles
        FROM roles WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["roles"] = dict(r.mappings().first())
    else:
        analytics["roles"] = {"total_roles": 0, "system_roles": 0, "custom_roles": 0}

    # ── Audit ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_audit_entries,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '24 hours') AS audit_24h,
            COUNT(*) FILTER (WHERE created_at >= CURRENT_DATE - INTERVAL '7 days') AS audit_7d,
            MAX(created_at)::text AS last_activity
        FROM audit_logs WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["audit"] = dict(r.mappings().first())
    else:
        analytics["audit"] = {"total_audit_entries": 0, "audit_24h": 0, "audit_7d": 0, "last_activity": None}

    # ── Recent activity ──
    r = await safe_query(db, """
        SELECT
            a.action,
            a.resource_type,
            a.resource_id,
            p.full_name AS actor_name,
            a.created_at::text,
            a.ip_address::text
        FROM audit_logs a
        LEFT JOIN profiles p ON p.id = a.actor_user_id
        WHERE a.tenant_id = :tid
        ORDER BY a.created_at DESC
        LIMIT 10
    """, p)
    if r:
        analytics["recent_activity"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["recent_activity"] = []

    # ── Settings count ──
    r = await safe_query(db, """
        SELECT COUNT(*) AS total_settings
        FROM tenant_settings WHERE tenant_id = :tid
    """, p)
    if r:
        row = r.mappings().first()
        analytics["settings_count"] = row["total_settings"] if row else 0
    else:
        analytics["settings_count"] = 0

    # ── Feature flags ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_flags,
            COUNT(*) FILTER (WHERE enabled = true) AS enabled_flags,
            COUNT(*) FILTER (WHERE enabled = false) AS disabled_flags
        FROM feature_flags WHERE tenant_id = :tid
    """, p)
    if r:
        analytics["features"] = dict(r.mappings().first())
    else:
        analytics["features"] = {"total_flags": 0, "enabled_flags": 0, "disabled_flags": 0}

    # ── Top events ──
    r = await safe_query(db, """
        SELECT
            e.id::text AS event_id,
            e.title AS event_name,
            e.status::text AS status,
            COUNT(i.id) AS total_invitations,
            COUNT(i.id) FILTER (WHERE i.checked_in_at IS NOT NULL) AS checked_in,
            COUNT(i.id) FILTER (WHERE i.rsvp_status = 'accepted') AS confirmed,
            e.start_date::text AS event_date
        FROM events e
        LEFT JOIN invitations i ON i.event_id = e.id
          AND i.status::text NOT IN ('revoked', 'expired')
          AND COALESCE(i.metadata->>'generation_deleted', 'false') <> 'true'
        WHERE e.tenant_id = :tid
           OR (
                CAST(:linked_organizer_id AS uuid) IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM event_operations o
                    WHERE o.event_id = e.id
                      AND o.provider_tenant_id = CAST(:linked_organizer_id AS uuid)
                      AND o.status <> 'cancelled'
                )
           )
        GROUP BY e.id, e.title, e.status, e.start_date, e.created_at
        ORDER BY COUNT(i.id) DESC, e.start_date DESC
        LIMIT 5
    """, p)
    if r:
        analytics["top_events"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["top_events"] = []

    # ── Members list ──
    r = await safe_query(db, """
        SELECT
            p.full_name,
            p.avatar_url,
            m.role::text,
            m.status::text,
            p.last_login_at::text AS last_login,
            m.created_at::text AS joined_at
        FROM memberships m
        JOIN profiles p ON p.id = m.user_id
        WHERE m.tenant_id = :tid
        ORDER BY m.created_at DESC
        LIMIT 20
    """, p)
    if r:
        analytics["members_list"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["members_list"] = []

    # Team-manager operational control metrics.
    r = await safe_query(db, """
        SELECT COUNT(*) FILTER (WHERE status IN ('pending','needs_information') AND created_at < now()-interval '24 hours') AS overdue_requests,
               COUNT(*) FILTER (WHERE status IN ('pending','needs_information')) AS new_requests
        FROM organizer_booking_requests WHERE provider_tenant_id=:tid
    """, p)
    analytics["request_sla"] = dict(r.mappings().first()) if r else {"overdue_requests": 0, "new_requests": 0}
    r = await safe_query(db, """
        SELECT COUNT(*) FILTER (WHERE o.deadline_at < now() AND o.status NOT IN ('completed','closed','cancelled')) AS overdue_operations,
               COUNT(*) FILTER (WHERE o.status IN ('planning','ready','in_progress')) AS active_operations
        FROM event_operations o LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid
        WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL)
    """, p)
    analytics["operation_sla"] = dict(r.mappings().first()) if r else {"overdue_operations": 0, "active_operations": 0}
    r = await safe_query(db, """
        SELECT COUNT(*) FILTER (WHERE t.due_at < now() AND t.status <> 'done') AS overdue_tasks,
               COUNT(*) FILTER (WHERE t.approval_required AND t.status='done' AND t.approved_by IS NULL) AS awaiting_approval
        FROM event_operation_tasks t JOIN event_operations o ON o.id=t.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid
        WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL)
    """, p)
    analytics["task_alerts"] = dict(r.mappings().first()) if r else {"overdue_tasks": 0, "awaiting_approval": 0}
    r = await safe_query(db, """
        SELECT COUNT(*) AS scans_today, COUNT(*) FILTER (WHERE result::text='success') AS successful_today,
               COUNT(*) FILTER (WHERE result::text<>'success') AS failed_today,
               COALESCE(ROUND(100.0*COUNT(*) FILTER (WHERE result::text='success')/NULLIF(COUNT(*),0)),0) AS quality_today
        FROM checkins c JOIN event_operations o ON o.event_id=c.event_id
        LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid
        WHERE o.provider_tenant_id=:tid AND c.created_at::date=CURRENT_DATE AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL)
    """, p)
    analytics["attendance_today"] = dict(r.mappings().first()) if r else {"scans_today": 0, "successful_today": 0, "failed_today": 0, "quality_today": 0}
    r = await safe_query(db, """
        SELECT om.user_id::text, p.full_name, om.role, COUNT(t.id) FILTER (WHERE t.status<>'done') AS open_tasks,
               COUNT(t.id) FILTER (WHERE t.status='done') AS completed_tasks
        FROM event_operation_members om JOIN profiles p ON p.id=om.user_id
        LEFT JOIN event_operation_tasks t ON t.operation_id=om.operation_id AND t.assigned_to=om.user_id
        JOIN event_operations o ON o.id=om.operation_id WHERE o.provider_tenant_id=:tid
          AND (o.project_manager_id=:uid OR om.user_id=:uid)
        GROUP BY om.user_id,p.full_name,om.role ORDER BY open_tasks DESC
    """, p)
    analytics["workload"] = [dict(row) for row in r.mappings().all()] if r else []
    r = await safe_query(db, """
        SELECT a.id::text AS attachment_id, a.file_name, a.size_bytes, a.created_at::text, o.id::text AS operation_id
        FROM event_operation_attachments a JOIN event_operations o ON o.id=a.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid
        WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL)
        ORDER BY a.created_at DESC LIMIT 10
    """, p)
    analytics["recent_files"] = [dict(row) for row in r.mappings().all()] if r else []
    r = await safe_query(db, """
        SELECT id::text, type, title, message, created_at::text, metadata
        FROM notifications WHERE tenant_id=:tid AND (user_id=:uid OR user_id IS NULL) AND read_at IS NULL
          AND (type LIKE '%critical%' OR type IN ('operation.escalated','operation.overdue','task.overdue','booking.overdue'))
        ORDER BY created_at DESC LIMIT 20
    """, p)
    analytics["critical_notifications"] = [dict(row) for row in r.mappings().all()] if r else []
    try:
        from app.services.usage_service import check_all_limits
        usage = await check_all_limits(db, tenant_id)
        analytics["plan_usage"] = usage.model_dump() if hasattr(usage, "model_dump") else usage
    except Exception:
        analytics["plan_usage"] = {"status": "unavailable"}

    return analytics
@router.get("/provider")
async def get_provider_dashboard(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Comprehensive analytics dashboard for Provider/Organizer tenants.
    Aggregates data across all events assigned via event_operations.
    """
    tenant_id = get_tenant_id_from_header(request)
    await require_permission(db, tenant_id, user.id, "reports.view")

    analytics = {}
    p = {"tid": tenant_id, "uid": str(user.id)}

    # ── Operations summary ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_operations,
            COUNT(*) FILTER (WHERE o.status IN ('planning','ready','in_progress')) AS active_operations,
            COUNT(*) FILTER (WHERE o.status = 'completed') AS completed_operations,
            COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancelled_operations,
            COALESCE(ROUND(AVG(o.progress) FILTER (WHERE o.status IN ('planning','ready','in_progress'))), 0) AS avg_progress
        FROM event_operations o
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
    """, p)
    if r:
        analytics["operations"] = dict(r.mappings().first())
    else:
        analytics["operations"] = {
            "total_operations": 0, "active_operations": 0,
            "completed_operations": 0, "cancelled_operations": 0, "avg_progress": 0,
        }

    # ── Booking funnel and response speed ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_requests,
            COUNT(*) FILTER (WHERE status = 'pending') AS pending_requests,
            COUNT(*) FILTER (WHERE status = 'needs_information') AS needs_information_requests,
            COUNT(*) FILTER (WHERE status = 'accepted') AS accepted_requests,
            COUNT(*) FILTER (WHERE status = 'rejected') AS rejected_requests,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_requests,
            COALESCE(ROUND(
                100.0 * COUNT(*) FILTER (WHERE status IN ('accepted','completed'))
                / NULLIF(COUNT(*) FILTER (WHERE status IN ('accepted','completed','rejected')), 0)
            ), 0) AS acceptance_rate,
            COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM (responded_at - created_at)) / 3600)
                FILTER (WHERE responded_at IS NOT NULL), 1), 0) AS avg_response_hours
        FROM organizer_booking_requests
        WHERE provider_tenant_id = :tid
    """, p)
    if r:
        analytics["booking_funnel"] = dict(r.mappings().first())
    else:
        analytics["booking_funnel"] = {
            "total_requests": 0, "pending_requests": 0, "needs_information_requests": 0,
            "accepted_requests": 0, "rejected_requests": 0, "completed_requests": 0,
            "acceptance_rate": 0, "avg_response_hours": 0,
        }

    # ── Monthly operation trend ──
    r = await safe_query(db, """
        SELECT
            to_char(date_trunc('month', b.starts_at), 'YYYY-MM') AS month,
            COUNT(*) AS operations,
            COUNT(*) FILTER (WHERE b.status = 'completed') AS completed,
            COALESCE(SUM(b.guest_count), 0) AS guest_capacity
        FROM organizer_booking_requests b
        JOIN event_operations o ON o.booking_id = b.id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE b.provider_tenant_id = :tid
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
          AND b.starts_at >= date_trunc('month', now()) - interval '5 months'
        GROUP BY date_trunc('month', b.starts_at)
        ORDER BY date_trunc('month', b.starts_at)
    """, p)
    analytics["monthly_trend"] = [dict(row) for row in r.mappings().all()] if r else []

    # ── Tasks summary (across all operations) ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_tasks,
            COUNT(*) FILTER (WHERE t.status = 'done') AS completed_tasks,
            COUNT(*) FILTER (WHERE t.status = 'in_progress') AS in_progress_tasks,
            COUNT(*) FILTER (WHERE t.status = 'blocked') AS blocked_tasks,
            COUNT(*) FILTER (WHERE t.status = 'todo') AS todo_tasks,
            COUNT(*) FILTER (WHERE t.due_at IS NOT NULL AND t.due_at < now() AND t.status != 'done') AS overdue_tasks,
            CASE WHEN COUNT(*) > 0
                THEN ROUND(100.0 * COUNT(*) FILTER (WHERE t.status = 'done') / COUNT(*))
                ELSE 0
            END AS completion_rate
        FROM event_operation_tasks t
        JOIN event_operations o ON o.id = t.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
    """, p)
    if r:
        analytics["tasks"] = dict(r.mappings().first())
    else:
        analytics["tasks"] = {
            "total_tasks": 0, "completed_tasks": 0, "in_progress_tasks": 0,
            "blocked_tasks": 0, "todo_tasks": 0, "overdue_tasks": 0, "completion_rate": 0,
        }

    r = await safe_query(db, """
        SELECT
            t.priority,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE t.status = 'done') AS done,
            COUNT(*) FILTER (WHERE t.status != 'done') AS open
        FROM event_operation_tasks t
        JOIN event_operations o ON o.id = t.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        GROUP BY t.priority
        ORDER BY CASE t.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END
    """, p)
    analytics["task_priority_breakdown"] = [dict(row) for row in r.mappings().all()] if r else []

    # ── Attendance stats (across all assigned events) ──
    r = await safe_query(db, """
        SELECT
            COUNT(*) AS total_invitations,
            COUNT(*) FILTER (WHERE i.status = 'checked_in') AS checked_in_count,
            COUNT(*) FILTER (WHERE i.ticket_class = 'vip') AS vip_total,
            COUNT(*) FILTER (WHERE i.ticket_class = 'vip' AND i.status = 'checked_in') AS vip_checked_in,
            COUNT(*) FILTER (WHERE i.ticket_class = 'normal') AS normal_total,
            COUNT(*) FILTER (WHERE i.ticket_class = 'normal' AND i.status = 'checked_in') AS normal_checked_in,
            COUNT(*) FILTER (WHERE i.status = 'sent') AS sent_count,
            COUNT(*) FILTER (WHERE i.status = 'viewed') AS viewed_count,
            COUNT(*) FILTER (WHERE i.status = 'accepted') AS accepted_count,
            COUNT(*) FILTER (WHERE i.status = 'declined') AS declined_count,
            CASE WHEN COUNT(*) FILTER (WHERE i.status NOT IN ('revoked','expired')) > 0
                THEN ROUND(100.0 * COUNT(*) FILTER (WHERE i.status = 'checked_in')
                     / COUNT(*) FILTER (WHERE i.status NOT IN ('revoked','expired')))
                ELSE 0
            END AS attendance_rate
        FROM invitations i
        JOIN event_operations o ON o.event_id = i.event_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND o.status NOT IN ('cancelled')
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
    """, p)
    if r:
        analytics["attendance"] = dict(r.mappings().first())
    else:
        analytics["attendance"] = {
            "total_invitations": 0, "checked_in_count": 0, "vip_total": 0,
            "vip_checked_in": 0, "normal_total": 0, "normal_checked_in": 0,
            "sent_count": 0, "viewed_count": 0, "accepted_count": 0,
            "declined_count": 0, "attendance_rate": 0,
        }

    # ── Gate distribution ──
    r = await safe_query(db, """
        SELECT
            g.id::text AS gate_id,
            g.name AS gate_name,
            e.title AS event_title,
            COUNT(c.id) FILTER (WHERE c.result = 'success') AS checkins,
            g.allowed_classes::text[] AS allowed_classes
        FROM event_gates g
        JOIN events e ON e.id = g.event_id
        JOIN event_operations o ON o.event_id = e.id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        LEFT JOIN checkins c ON c.gate_id = g.id
        WHERE o.provider_tenant_id = :tid
          AND o.status NOT IN ('cancelled')
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        GROUP BY g.id, g.name, e.title, g.allowed_classes
        ORDER BY checkins DESC
    """, p)
    if r:
        analytics["gates"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["gates"] = []

    # ── Team members ──
    r = await safe_query(db, """
        SELECT
            COUNT(DISTINCT m.user_id) AS total_members
        FROM memberships m
        WHERE m.tenant_id = :tid AND m.status = 'active'
    """, p)
    if r:
        analytics["team"] = dict(r.mappings().first())
    else:
        analytics["team"] = {"total_members": 0}

    # ── Top performers (members with most completed tasks) ──
    r = await safe_query(db, """
        SELECT
            p.full_name,
            COUNT(*) AS completed_tasks,
            COUNT(*) FILTER (WHERE t.completed_at IS NOT NULL
                AND t.due_at IS NOT NULL
                AND t.completed_at <= t.due_at) AS on_time_tasks
        FROM event_operation_tasks t
        JOIN event_operations o ON o.id = t.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        JOIN profiles p ON p.id = t.assigned_to
        WHERE o.provider_tenant_id = :tid
          AND t.status = 'done'
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        GROUP BY p.full_name
        ORDER BY completed_tasks DESC
        LIMIT 10
    """, p)
    if r:
        analytics["top_performers"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["top_performers"] = []

    # ── Scan leaderboard (members with most accepted scans) ──
    r = await safe_query(db, """
        SELECT
            p.full_name AS scanner_name,
            p.id::text AS scanner_id,
            COUNT(*) FILTER (WHERE c.result = 'success') AS accepted_scans,
            COUNT(*) FILTER (WHERE c.result = 'duplicate') AS duplicate_scans,
            COUNT(*) FILTER (WHERE c.result = 'rejected') AS rejected_scans,
            COUNT(*) AS total_scans
        FROM checkins c
        JOIN event_gates g ON g.id = c.gate_id
        JOIN event_operations o ON o.event_id = g.event_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        LEFT JOIN profiles p ON p.id = c.scanned_by
        WHERE o.provider_tenant_id = :tid
          AND o.status NOT IN ('cancelled')
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        GROUP BY p.full_name, p.id
        ORDER BY accepted_scans DESC, total_scans DESC
        LIMIT 10
    """, p)
    if r:
        analytics["scan_leaderboard"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["scan_leaderboard"] = []

    r = await safe_query(db, """
        SELECT
            COUNT(*) FILTER (WHERE c.result = 'success') AS success_scans,
            COUNT(*) FILTER (WHERE c.result = 'duplicate') AS duplicate_scans,
            COUNT(*) FILTER (WHERE c.result = 'rejected') AS rejected_scans,
            COUNT(*) AS total_scans,
            COALESCE(ROUND(
                100.0 * COUNT(*) FILTER (WHERE c.result = 'success') / NULLIF(COUNT(*), 0)
            ), 0) AS scan_success_rate
        FROM checkins c
        JOIN event_operations o ON o.event_id = c.event_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND o.status NOT IN ('cancelled')
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
    """, p)
    analytics["scan_quality"] = dict(r.mappings().first()) if r else {
        "success_scans": 0, "duplicate_scans": 0, "rejected_scans": 0,
        "total_scans": 0, "scan_success_rate": 0,
    }

    # ── Upcoming events (assigned and not completed) ──
    r = await safe_query(db, """
        SELECT
            e.id::text AS event_id,
            o.id::text AS operation_id,
            e.title,
            e.start_date::text,
            e.status::text AS event_status,
            o.status::text AS operation_status,
            o.progress,
            rt.name AS client_name,
            (SELECT COUNT(*) FROM invitations i WHERE i.event_id = e.id) AS invitation_count,
            (SELECT COUNT(*) FROM invitations i WHERE i.event_id = e.id AND i.status = 'checked_in') AS checked_in_count,
            (SELECT COUNT(*) FROM event_gates g WHERE g.event_id = e.id) AS gate_count
        FROM event_operations o
        JOIN events e ON e.id = o.event_id
        JOIN tenants rt ON rt.id = o.requester_tenant_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        WHERE o.provider_tenant_id = :tid
          AND o.status NOT IN ('completed', 'closed', 'cancelled')
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        ORDER BY e.start_date ASC
        LIMIT 10
    """, p)
    if r:
        analytics["upcoming_events"] = [dict(row) for row in r.mappings().all()]
    else:
        analytics["upcoming_events"] = []

    # ── Recent activity ──
    r = await safe_query(db, """
        SELECT
            a.action,
            a.entity_type,
            a.entity_id,
            a.details,
            p.full_name AS actor_name,
            a.created_at::text
        FROM event_operation_activity a
        JOIN event_operations o ON o.id = a.operation_id
        LEFT JOIN event_operation_members om ON om.operation_id = o.id AND om.user_id = :uid
        LEFT JOIN profiles p ON p.id = a.actor_user_id
        WHERE o.provider_tenant_id = :tid
          AND (o.project_manager_id = :uid OR om.user_id IS NOT NULL)
        ORDER BY a.created_at DESC
        LIMIT 20
    """, p)
    if r:
        analytics["recent_activity"] = [dict(row) for row in r.mappings().all()]
    # ── Team permissions analysis ──
    members_res = await safe_query(db, """
        SELECT
            m.user_id::text,
            p.full_name,
            p.avatar_url,
            m.role AS system_role,
            m.status,
            ARRAY(
                SELECT DISTINCT rp.permission_key
                FROM public.membership_roles mr
                JOIN public.role_permissions rp ON rp.role_id = mr.role_id
                WHERE mr.tenant_id = :tid AND mr.user_id = m.user_id
            ) AS role_permissions
        FROM public.memberships m
        JOIN public.profiles p ON p.id = m.user_id
        WHERE m.tenant_id = :tid AND m.status = 'active'
    """, p)
    if members_res:
        members_data = []
        for row in members_res.mappings().all():
            m_dict = dict(row)
            if m_dict["system_role"] in ("owner", "admin"):
                all_perms = await db.execute(text("SELECT key FROM public.permissions"))
                m_dict["permissions"] = [r[0] for r in all_perms.fetchall()]
            else:
                m_dict["permissions"] = m_dict["role_permissions"]
            members_data.append(m_dict)
        analytics["team_permissions"] = members_data
    else:
        analytics["team_permissions"] = []

    # Provider dashboard operational alerts not covered by the legacy aggregates.
    r = await safe_query(db, "SELECT COUNT(*) FILTER (WHERE status IN ('pending','needs_information')) AS new_requests, COUNT(*) FILTER (WHERE status IN ('pending','needs_information') AND created_at < now()-interval '24 hours') AS overdue_requests FROM organizer_booking_requests WHERE provider_tenant_id=:tid", p)
    analytics["request_sla"] = dict(r.mappings().first()) if r else {"new_requests": 0, "overdue_requests": 0}
    r = await safe_query(db, "SELECT COUNT(*) FILTER (WHERE t.due_at < now() AND t.status<>'done') AS overdue_tasks, COUNT(*) FILTER (WHERE t.approval_required AND t.status='done' AND t.approved_by IS NULL) AS awaiting_approval FROM event_operation_tasks t JOIN event_operations o ON o.id=t.operation_id LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL)", p)
    analytics["task_alerts"] = dict(r.mappings().first()) if r else {"overdue_tasks": 0, "awaiting_approval": 0}
    r = await safe_query(db, "SELECT om.user_id::text, p.full_name, om.role, COUNT(t.id) FILTER (WHERE t.status<>'done') AS open_tasks, COUNT(t.id) FILTER (WHERE t.status='done') AS completed_tasks FROM event_operation_members om JOIN profiles p ON p.id=om.user_id LEFT JOIN event_operation_tasks t ON t.operation_id=om.operation_id AND t.assigned_to=om.user_id JOIN event_operations o ON o.id=om.operation_id WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id=:uid) GROUP BY om.user_id,p.full_name,om.role ORDER BY open_tasks DESC", p)
    analytics["workload"] = [dict(row) for row in r.mappings().all()] if r else []
    r = await safe_query(db, "SELECT a.id::text AS attachment_id,a.file_name,a.size_bytes,a.created_at::text,o.id::text AS operation_id FROM event_operation_attachments a JOIN event_operations o ON o.id=a.operation_id LEFT JOIN event_operation_members om ON om.operation_id=o.id AND om.user_id=:uid WHERE o.provider_tenant_id=:tid AND (o.project_manager_id=:uid OR om.user_id IS NOT NULL) ORDER BY a.created_at DESC LIMIT 10", p)
    analytics["recent_files"] = [dict(row) for row in r.mappings().all()] if r else []
    r = await safe_query(db, "SELECT id::text,type,title,message,created_at::text,metadata FROM notifications WHERE tenant_id=:tid AND (user_id=:uid OR user_id IS NULL) AND read_at IS NULL AND (type LIKE '%critical%' OR type IN ('operation.escalated','operation.overdue','task.overdue','booking.overdue')) ORDER BY created_at DESC LIMIT 20", p)
    analytics["critical_notifications"] = [dict(row) for row in r.mappings().all()] if r else []
    try:
        from app.services.usage_service import check_all_limits
        usage = await check_all_limits(db, tenant_id)
        analytics["plan_usage"] = usage.model_dump() if hasattr(usage, "model_dump") else usage
    except Exception:
        analytics["plan_usage"] = {"status": "unavailable"}

    return analytics
