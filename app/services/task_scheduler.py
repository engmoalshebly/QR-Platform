"""Background scheduler for task overdue / due-soon notifications
and the subscription lifecycle (renewal reminders, expiry, cleanup).

Runs a single asyncio loop inside the FastAPI process (started from the
app lifespan; `scheduler_runner` remains available for standalone runs).
Checks every hour for:
  - operation tasks that are overdue or due within 24h
  - operations that exceeded their SLA / events starting within 24h
  - subscriptions expiring in 7/3/1 days (renewal reminders)
  - expired subscriptions (downgrade to starter + notify managers)
  - abandoned pending_subscriptions rows (TTL cleanup)

Notifications are deduped via notifications.metadata->>'dedup_key' —
inserted atomically (INSERT ... WHERE NOT EXISTS) so concurrent scheduler
instances cannot double-notify.
"""
import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.services.notification_service import create_notification
from app.config import get_settings

from app.services import email_service

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = get_settings().scheduler_interval_seconds
DUE_SOON_HOURS = 24

_OVERDUE_SQL = """
    SELECT t.id, t.title, t.due_at, t.operation_id, t.assigned_to, o.provider_tenant_id
    FROM event_operation_tasks t
    JOIN event_operations o ON o.id = t.operation_id
    WHERE t.status <> 'done'
      AND t.due_at IS NOT NULL
      AND t.due_at < now()
"""

_DUE_SOON_SQL = """
    SELECT t.id, t.title, t.due_at, t.operation_id, t.assigned_to, o.provider_tenant_id
    FROM event_operation_tasks t
    JOIN event_operations o ON o.id = t.operation_id
    WHERE t.status <> 'done'
      AND t.due_at IS NOT NULL
      AND t.due_at BETWEEN now() AND now() + (:hours || ' hours')::interval
"""

_DEDUP_CHECK_SQL = """
    SELECT 1 FROM notifications
    WHERE tenant_id = :tid AND (user_id = :uid OR user_id IS NULL)
      AND type = :ntype AND metadata->>'dedup_key' = :dedup
    LIMIT 1
"""

async def _scan_sla_and_events() -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text("""
          SELECT o.id AS operation_id, o.provider_tenant_id, o.title, o.sla_due_at, 'operation.sla' AS kind
          FROM event_operations o WHERE o.sla_due_at IS NOT NULL AND o.sla_due_at < now()
            AND o.status NOT IN ('completed','closed','cancelled')
          UNION ALL
          SELECT o.id, o.provider_tenant_id, COALESCE(e.title,o.title), e.start_date, 'event.upcoming'
          FROM event_operations o JOIN events e ON e.id=o.event_id
          WHERE e.start_date BETWEEN now() AND now()+interval '24 hours'
            AND o.status NOT IN ('completed','closed','cancelled')
        """))
        emitted = 0
        for row in rows.mappings().all():
            dedup = f"{row['kind']}:{row['operation_id']}:{row['kind']}"
            if await _already_notified(db, row['provider_tenant_id'], None, row['kind'], dedup): continue
            is_sla = row['kind'] == 'operation.sla'
            await create_notification(db, row['provider_tenant_id'], row['kind'],
                "تجاوز SLA" if is_sla else "موعد الحدث قريب",
                f"العملية «{row['title'] or ''}» تجاوزت SLA" if is_sla else f"موعد الحدث «{row['title'] or ''}» خلال 24 ساعة",
                link=f"/team-events/{row['operation_id']}", metadata={"operation_id": str(row['operation_id']), "dedup_key": dedup})
            emitted += 1
        if emitted: await db.commit()
        return emitted


async def _already_notified(db, tenant_id, user_id, ntype: str, dedup: str) -> bool:
    result = await db.execute(text(_DEDUP_CHECK_SQL), {
        "tid": str(tenant_id), "uid": str(user_id) if user_id else None,
        "ntype": ntype, "dedup": dedup,
    })
    return result.first() is not None


async def _scan(kind: str, sql: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(text(sql), {"hours": str(DUE_SOON_HOURS)})
        emitted = 0
        for row in rows.mappings().all():
            tenant_id = row["provider_tenant_id"]
            user_id = row["assigned_to"]
            dedup = f"{kind}:{row['id']}"
            if await _already_notified(db, tenant_id, user_id, f"task.{kind}", dedup):
                continue
            title = "مهمة متأخرة" if kind == "delayed" else "مهمة مستحقة قريباً"
            when = row["due_at"].strftime("%Y-%m-%d %H:%M") if row["due_at"] else ""
            message = f"المهمة «{row['title']}» {('متأخرة' if kind == 'delayed' else 'مستحقة')} — موعد الاستحقاق {when}"
            await create_notification(
                db, tenant_id, f"task.{kind}", title, message,
                user_id=user_id if user_id else None,
                link=f"/team-events/{row['operation_id']}?tab=tasks",
                metadata={"operation_id": str(row["operation_id"]), "task_id": str(row["id"]), "dedup_key": dedup},
            )
            emitted += 1
        if emitted:
            await db.commit()
    return emitted


async def _tick() -> None:
    try:
        delayed = await _scan("delayed", _OVERDUE_SQL)
        soon = await _scan("due_soon", _DUE_SOON_SQL)
        if delayed or soon:
            logger.info("task scheduler: %d overdue, %d due-soon notifications emitted", delayed, soon)
        extra = await _scan_sla_and_events()
        if extra: logger.info("scheduler emitted %d SLA/event notifications", extra)
    except Exception:
        logger.exception("task scheduler tick failed")
    try:
        await _scan_subscriptions()
    except Exception:
        logger.exception("subscription scheduler tick failed")


# ──────────────────────────────────────────
# Subscription lifecycle
# ──────────────────────────────────────────

_RENEWAL_REMINDER_DAYS = (7, 3, 1)

_EXPIRING_SQL = """
    SELECT s.id, s.tenant_id, s.current_period_end, p.name AS plan_name
    FROM subscriptions s
    JOIN plans p ON p.id = s.plan_id
    WHERE s.status = 'active'
      AND s.cancel_at_period_end = false
      AND s.current_period_end IS NOT NULL
      AND s.current_period_end BETWEEN now() AND now() + interval '7 days'
"""

_EXPIRING_CUSTOM_SQL = """
    SELECT cp.id, cp.tenant_id, cp.valid_until AS current_period_end, p.name AS plan_name
    FROM custom_plans cp
    JOIN plans p ON p.id = cp.base_plan_id
    WHERE cp.status = 'active'
      AND cp.activated_at IS NOT NULL
      AND cp.valid_until IS NOT NULL
      AND cp.valid_until BETWEEN now() AND now() + interval '7 days'
"""

_OWNER_SQL = """
    SELECT u.email, COALESCE(p.full_name, u.email) AS full_name
    FROM memberships m
    JOIN auth.users u ON u.id = m.user_id
    LEFT JOIN profiles p ON p.id = m.user_id
    WHERE m.tenant_id = :tid AND m.role = 'owner' AND m.status = 'active'
    LIMIT 1
"""


async def _email_owner(db, tenant_id: str, sender, *args) -> None:
    """Best effort: a mail problem must never break the scheduler tick."""
    try:
        owner = (await db.execute(text(_OWNER_SQL), {"tid": str(tenant_id)})).mappings().first()
        if not owner or not owner["email"]:
            return
        await asyncio.to_thread(sender, owner["email"], *args, owner["full_name"])
    except Exception:
        logger.exception("subscription e-mail could not be sent tenant=%s", tenant_id)


# Atomic dedup: the insert and the duplicate check are one statement, so two
# overlapping scheduler instances cannot emit the same reminder twice.
_REMINDER_INSERT_SQL = """
    INSERT INTO notifications (tenant_id, user_id, type, title, message, link, metadata)
    SELECT :tid, NULL, 'subscription.renewal_reminder', :title, :message,
           '/settings?tab=billing', CAST(:metadata AS jsonb)
    WHERE NOT EXISTS (
        SELECT 1 FROM notifications
        WHERE tenant_id = :tid AND type = 'subscription.renewal_reminder'
          AND metadata->>'dedup_key' = :dedup
    )
"""


async def _scan_subscriptions() -> None:
    from app.services.subscription_engine import get_subscription_engine
    engine = get_subscription_engine()

    async with AsyncSessionLocal() as db:
        # 1) Renewal reminders at 7 / 3 / 1 days before period end, for standard
        #    subscriptions and for activated custom plans.
        now = datetime.now(timezone.utc)
        candidates = []
        for kind, sql in (("sub", _EXPIRING_SQL), ("custom", _EXPIRING_CUSTOM_SQL)):
            for row in (await db.execute(text(sql))).mappings().all():
                candidates.append((kind, row))
        emitted = 0
        to_email = []
        for kind, row in candidates:
            end = row["current_period_end"]
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            days_left = math.ceil((end - now).total_seconds() / 86400)
            if days_left not in _RENEWAL_REMINDER_DAYS:
                continue
            dedup = f"{kind}.renew:{row['id']}:{days_left}"
            if days_left == 1:
                title = "اشتراكك ينتهي غداً"
                when = "غداً"
            else:
                title = f"تبقى {days_left} أيام على انتهاء اشتراكك"
                when = f"خلال {days_left} أيام"
            noun = "باقتك المخصّصة" if kind == "custom" else "اشتراكك في باقة"
            result = await db.execute(text(_REMINDER_INSERT_SQL), {
                "tid": str(row["tenant_id"]),
                "title": title,
                "message": (
                    f"{noun} «{row['plan_name']}» ينتهي {when}. "
                    "جدّد الآن لتفادي التحويل التلقائي إلى الباقة المجانية."
                ),
                "metadata": json.dumps({"subscription_id": str(row["id"]), "days_left": days_left,
                                        "dedup_key": dedup, "kind": kind}),
                "dedup": dedup,
            })
            if result.rowcount:
                emitted += result.rowcount
                to_email.append((str(row["tenant_id"]), row["plan_name"], days_left, end.date().isoformat()))
        if emitted:
            await db.commit()
            logger.info("scheduler emitted %d subscription renewal reminders", emitted)
            for tid, plan_name, days_left, until in to_email:  # only on first emission (dedup)
                await _email_owner(db, tid, email_service.send_subscription_expiring_email, plan_name, days_left, until)

        # 2) Expire overdue subscriptions → downgrade to starter + notify managers
        downgraded = await engine.check_expired_subscriptions(db)  # commits internally
        expired_to_email = []
        for tid in downgraded:
            inserted = await db.execute(text("""
                INSERT INTO notifications (tenant_id, user_id, type, title, message, link, metadata)
                SELECT :tid, NULL, 'subscription.expired',
                       'انتهى الاشتراك',
                       'انتهت فترة اشتراكك وتم تحويل مساحة العمل إلى الباقة المجانية. جدّد اشتراكك لاستعادة المزايا.',
                       '/settings?tab=billing', CAST(:metadata AS jsonb)
                WHERE NOT EXISTS (
                    SELECT 1 FROM notifications
                    WHERE tenant_id = :tid AND type = 'subscription.expired'
                      AND metadata->>'dedup_key' = :dedup
                )
            """), {
                "tid": tid,
                "metadata": json.dumps({"dedup_key": f"sub.expired:{tid}:{now.date().isoformat()}"}),
                "dedup": f"sub.expired:{tid}:{now.date().isoformat()}",
            })
            if inserted.rowcount:
                last = (await db.execute(text("""
                    SELECT p.name FROM subscriptions s JOIN plans p ON p.id = s.plan_id
                    WHERE s.tenant_id = :tid AND s.status = 'canceled'
                    ORDER BY s.canceled_at DESC NULLS LAST, s.created_at DESC LIMIT 1
                """), {"tid": tid})).scalar()
                expired_to_email.append((tid, last or "المدفوعة"))
        if downgraded:
            await db.commit()
            logger.info("scheduler downgraded %d expired subscriptions", len(downgraded))
            for tid, plan_name in expired_to_email:
                await _email_owner(db, tid, email_service.send_subscription_expired_email, plan_name)

        # 3) Cleanup abandoned pending subscription rows (OTP never confirmed)
        await engine.cleanup_pending_subscriptions(db)


async def run_forever() -> None:
    while True:
        await _tick()
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
