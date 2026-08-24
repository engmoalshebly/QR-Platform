"""
Tenant Provisioning Service.
Handles all setup when a new tenant is created:
- Default roles (Admin, Member, Designer, Check-in Staff, Viewer) with permissions
- Default settings (timezone, language, invitation defaults, etc.)
- Default feature flags for invitation platform
- Owner membership + role assignment
"""
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import re
import secrets

logger = logging.getLogger(__name__)


async def ensure_linked_institution_workspace(
    db: AsyncSession,
    organizer_tenant_id: UUID,
    owner_user_id: UUID,
    organizer_name: str,
) -> UUID:
    """Create the institution half of an organizer account exactly once.

    The organizer and institution deliberately have separate tenants, so event
    ownership and operational data remain isolated.  They share the same human
    owner and are tied through ``workspace_links``; no second auth account,
    password, or subscription is created.
    """
    existing = await db.execute(text("""
        SELECT institution_tenant_id
        FROM workspace_links
        WHERE organizer_tenant_id = :organizer_id AND status = 'active'
        LIMIT 1
    """), {"organizer_id": str(organizer_tenant_id)})
    linked_id = existing.scalar()
    if linked_id:
        return UUID(str(linked_id))

    base_slug = re.sub(r"[^a-z0-9]+", "-", organizer_name.lower()).strip("-")
    if len(base_slug) < 3:
        base_slug = "organization"
    slug = f"{base_slug[:34]}-institution-{secrets.token_hex(3)}"
    institution_name = f"{organizer_name} - المؤسسة"

    institution_result = await db.execute(text("""
        INSERT INTO tenants (slug, name, created_by, workspace_type, metadata)
        VALUES (
            :slug, :name, :owner_id, 'institution',
            jsonb_build_object('linked_organizer_tenant_id', CAST(:organizer_id AS text))
        )
        RETURNING id
    """), {
        "slug": slug,
        "name": institution_name,
        "owner_id": str(owner_user_id),
        "organizer_id": str(organizer_tenant_id),
    })
    institution_id = UUID(str(institution_result.scalar_one()))

    await db.execute(text("""
        INSERT INTO memberships (tenant_id, user_id, role, status)
        VALUES (:tenant_id, :owner_id, 'owner', 'active')
        ON CONFLICT DO NOTHING
    """), {"tenant_id": str(institution_id), "owner_id": str(owner_user_id)})

    # This supplies the normal institution roles, permissions, settings and
    # feature flags. Billing remains owned by the organizer workspace through
    # workspace_links.billing_tenant_id.
    await provision_tenant_manual(db, institution_id, owner_user_id)

    await db.execute(text("""
        INSERT INTO workspace_links
            (organizer_tenant_id, institution_tenant_id, owner_user_id, billing_tenant_id)
        VALUES (:organizer_id, :institution_id, :owner_id, :organizer_id)
    """), {
        "organizer_id": str(organizer_tenant_id),
        "institution_id": str(institution_id),
        "owner_id": str(owner_user_id),
    })
    return institution_id


async def provision_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    owner_user_id: UUID,
) -> None:
    """
    Full provisioning for a new tenant.
    Calls the DB function that creates roles, permissions, settings.
    """
    await db.execute(
        text("SELECT public.provision_tenant(:tid, :uid)"),
        {"tid": str(tenant_id), "uid": str(owner_user_id)},
    )
    await ensure_team_manager_role(db, tenant_id, owner_user_id)
    logger.info("Provisioned tenant %s with owner %s", tenant_id, owner_user_id)


async def ensure_team_manager_role(db: AsyncSession, tenant_id: UUID, owner_user_id: UUID) -> None:
    """Create/assign team_manager only for approved organizer tenants."""
    approved = await db.execute(text("""
        SELECT 1 FROM organization_requests
        WHERE created_tenant_id = :tid AND status = 'approved'
          AND created_user_id = :uid
        LIMIT 1
    """), {"tid": str(tenant_id), "uid": str(owner_user_id)})
    if not approved.first():
        return
    role = await db.execute(text("""
        INSERT INTO roles (tenant_id, name, description, is_system_role)
        VALUES (:tid, 'team_manager', 'مسؤول فريق التشغيل وإدارة الحجوزات والعمليات', true)
        ON CONFLICT DO NOTHING
        RETURNING id
    """), {"tid": str(tenant_id)})
    role_id = role.scalar()
    if not role_id:
        role_id = (await db.execute(text("SELECT id FROM roles WHERE tenant_id=:tid AND name='team_manager' LIMIT 1"), {"tid": str(tenant_id)})).scalar()
    await db.execute(text("""
        INSERT INTO role_permissions (role_id, permission_key)
        SELECT :rid, key FROM permissions WHERE key = ANY(:keys)
        ON CONFLICT DO NOTHING
    """), {"rid": str(role_id), "keys": [
        'reports.view', 'bookings.view', 'bookings.respond', 'bookings.manage',
        'operations.view', 'operations.manage', 'operations.members', 'operations.attachments',
        'operations.tasks.view', 'operations.tasks.create', 'operations.tasks.update_own',
        'operations.tasks.update_any', 'operations.tasks.delete',
        'operations.tasks.delete_completed', 'operations.tasks.assign',
        'operations.tasks.comment', 'operations.tasks.approve',
        'operations.edit', 'operations.progress.update', 'operations.status.change',
        'operations.escalate', 'operations.close',
        'operations.attachments.view', 'operations.attachments.upload',
        'operations.attachments.delete', 'operations.attachments.download',
        'notifications.view', 'events.view', 'guests.view', 'invitations.view',
        'gates.view', 'gates.manage', 'checkin.view', 'checkin.scan', 'checkin.manual',
        'ui.organizer.nav.home', 'ui.organizer.nav.requests',
        'ui.organizer.nav.operations', 'ui.organizer.nav.members',
        'ui.organizer.nav.groups', 'ui.organizer.nav.settings',
        'ui.operation.tab.overview', 'ui.operation.tab.tasks',
        'ui.operation.tab.team', 'ui.operation.tab.guests',
        'ui.operation.tab.gates', 'ui.operation.tab.live',
        'ui.operation.tab.files', 'ui.operation.tab.activity'
    ]})
    await db.execute(text("""
        INSERT INTO membership_roles (tenant_id, user_id, role_id)
        VALUES (:tid, :uid, :rid) ON CONFLICT DO NOTHING
    """), {"tid": str(tenant_id), "uid": str(owner_user_id), "rid": str(role_id)})


async def provision_tenant_manual(
    db: AsyncSession,
    tenant_id: UUID,
    owner_user_id: UUID,
) -> None:
    """
    Manual provisioning (fallback if DB function not available).
    Creates default roles + permissions + settings via SQL.
    """
    # Create Admin role
    admin_result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, 'Admin', 'مدير كامل الصلاحيات', true)
            RETURNING id
        """),
        {"tid": str(tenant_id)},
    )
    admin_role_id = admin_result.scalar()

    # Assign all permissions to Admin
    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(admin_role_id)},
    )

    # Create Member role (event manager)
    member_result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, 'Member', 'مدير أحداث ودعوات', true)
            RETURNING id
        """),
        {"tid": str(tenant_id)},
    )
    member_role_id = member_result.scalar()

    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'users.view', 'members.view', 'settings.view', 'reports.view',
                'files.upload', 'files.view', 'notifications.view', 'tenant.view',
                'events.create', 'events.view', 'events.edit',
                'templates.view', 'templates.create', 'templates.edit',
                'invitations.create', 'invitations.view', 'invitations.send',
                'guests.view', 'guests.create', 'guests.edit', 'guests.import',
                'checkin.scan', 'checkin.view',
                'teams.view', 'teams.request', 'gates.view',
                'batches.create', 'batches.view'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(member_role_id)},
    )
    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key LIKE 'ui.%'
              AND key NOT IN (
                'ui.event.action.delete', 'ui.gates.action.delete',
                'ui.invitations.action.revoke', 'ui.templates.action.delete',
                'ui.members.action.create', 'ui.members.action.edit', 'ui.members.action.delete',
                'ui.roles.action.manage', 'ui.teams.action.archive'
              )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(member_role_id)},
    )

    # Create Designer role
    designer_result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, 'Designer', 'مصمم القوالب', true)
            RETURNING id
        """),
        {"tid": str(tenant_id)},
    )
    designer_role_id = designer_result.scalar()

    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'templates.view', 'templates.create', 'templates.edit',
                'files.upload', 'files.view',
                'events.view', 'invitations.view', 'tenant.view'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(designer_role_id)},
    )
    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'ui.nav.dashboard', 'ui.nav.events',
                'ui.event.tab.analytics', 'ui.event.tab.templates', 'ui.event.tab.settings',
                'ui.templates.action.create', 'ui.templates.action.edit', 'ui.templates.action.design'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(designer_role_id)},
    )

    # Create Check-in Staff role
    checkin_result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, 'Check-in Staff', 'موظف استقبال ومسح', true)
            RETURNING id
        """),
        {"tid": str(tenant_id)},
    )
    checkin_role_id = checkin_result.scalar()

    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'checkin.scan', 'checkin.view', 'checkin.manual',
                'events.view', 'invitations.view', 'guests.view',
                'gates.view', 'tenant.view'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(checkin_role_id)},
    )
    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'ui.nav.dashboard', 'ui.nav.checkin', 'ui.nav.events',
                'ui.event.tab.analytics',
                'ui.checkin.action.scan', 'ui.checkin.action.manual'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(checkin_role_id)},
    )

    # Create Viewer role (read-only)
    viewer_result = await db.execute(
        text("""
            INSERT INTO roles (tenant_id, name, description, is_system_role)
            VALUES (:tid, 'Viewer', 'مشاهد فقط', true)
            RETURNING id
        """),
        {"tid": str(tenant_id)},
    )
    viewer_role_id = viewer_result.scalar()

    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'users.view', 'members.view', 'reports.view',
                'files.view', 'notifications.view', 'tenant.view',
                'events.view', 'invitations.view', 'guests.view',
                'checkin.view', 'templates.view', 'teams.view', 'gates.view',
                'batches.view'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(viewer_role_id)},
    )
    await db.execute(
        text("""
            INSERT INTO role_permissions (role_id, permission_key)
            SELECT :rid, key FROM permissions
            WHERE key IN (
                'ui.nav.dashboard', 'ui.nav.events', 'ui.nav.invitations', 'ui.nav.checkin',
                'ui.event.tab.analytics', 'ui.event.tab.rsvp', 'ui.event.tab.final', 'ui.event.tab.barcodes'
            )
            ON CONFLICT DO NOTHING
        """),
        {"rid": str(viewer_role_id)},
    )

    # Assign Admin role to owner
    await db.execute(
        text("""
            INSERT INTO membership_roles (tenant_id, user_id, role_id)
            VALUES (:tid, :uid, :rid)
            ON CONFLICT DO NOTHING
        """),
        {"tid": str(tenant_id), "uid": str(owner_user_id), "rid": str(admin_role_id)},
    )

    # Default settings
    default_settings = [
        ("timezone", '"Asia/Riyadh"'),
        ("language", '"ar"'),
        ("date_format", '"YYYY-MM-DD"'),
        ("time_format", '"HH:mm"'),
        ("logo_url", '""'),
        ("favicon_url", '""'),
        ("primary_color", '"#6366f1"'),
        ("secondary_color", '"#8b5cf6"'),
        ("company_email", '""'),
        ("company_phone", '""'),
        ("company_address", '""'),
        ("currency", '"SAR"'),
        ("notifications_enabled", "true"),
        ("email_notifications", "true"),
        ("sms_notifications", "false"),
        ("two_factor_required", "false"),
        ("session_timeout_minutes", "60"),
        ("max_login_attempts", "5"),
        ("default_ticket_class", '"normal"'),
        ("default_invitation_expiry_days", "30"),
        ("allow_reentry_default", "false"),
        ("checkin_sound_enabled", "true"),
        ("invitation_sms_template", '""'),
        ("invitation_email_template", '""'),
    ]
    for key, value in default_settings:
        await db.execute(
            text("""
                INSERT INTO tenant_settings (tenant_id, key, value)
                VALUES (:tid, :key, CAST(:val AS jsonb))
                ON CONFLICT DO NOTHING
            """),
            {"tid": str(tenant_id), "key": key, "val": value},
        )

    # Default feature flags (invitation platform)
    default_flags = [
        ("designed_templates", False, '{"description": "قوالب بتصميم وإحداثيات"}'),
        ("rsvp", False, '{"description": "تأكيد الحضور RSVP"}'),
        ("multi_gate", False, '{"description": "بوابات متعددة"}'),
        ("sms_delivery", False, '{"description": "إرسال SMS"}'),
        ("whatsapp_delivery", False, '{"description": "إرسال WhatsApp"}'),
        ("email_delivery", True, '{"description": "إرسال بريد إلكتروني"}'),
        ("pdf_export", False, '{"description": "تصدير PDF عالي الجودة"}'),
        ("bulk_import", False, '{"description": "استيراد ضيوف جماعي"}'),
        ("advanced_reports", False, '{"description": "تقارير متقدمة"}'),
        ("api_access", False, '{"description": "الوصول لـ REST API"}'),
        ("custom_domain", False, '{"description": "نطاق مخصص"}'),
        ("white_label", False, '{"description": "إزالة العلامة التجارية"}'),
        ("audit_log", True, '{"description": "سجل التدقيق"}'),
        ("multi_language", True, '{"description": "دعم متعدد اللغات"}'),
        ("seating_management", False, '{"description": "إدارة المقاعد والطاولات"}'),
        ("vip_invitations", True, '{"description": "دعوات VIP"}'),
    ]
    for flag_key, enabled, metadata in default_flags:
        await db.execute(
            text("""
                INSERT INTO feature_flags (tenant_id, flag_key, enabled, metadata)
                VALUES (:tid, :key, :enabled, CAST(:meta AS jsonb))
                ON CONFLICT DO NOTHING
            """),
            {"tid": str(tenant_id), "key": flag_key, "enabled": enabled, "meta": metadata},
        )

    await ensure_team_manager_role(db, tenant_id, owner_user_id)
    logger.info("Manually provisioned tenant %s with owner %s", tenant_id, owner_user_id)
