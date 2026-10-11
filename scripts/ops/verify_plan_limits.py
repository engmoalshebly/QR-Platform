"""Behavioural check of plan limits, month rollover and the subscription lifecycle.

DESTRUCTIVE: it edits subscriptions and counters.  Run it ONLY against a
throw-away copy of the database (see RUNBOOK "Verifying plan limits"), never
against production.  The tenant ids below are those of the 2026-10 production
data; adjust them to the clone you restore.
"""
import asyncio, json
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import text
from app.database import AsyncSessionLocal

T_S = UUID("03c0569c-675d-40cf-980d-257b24f2ec46")   # standalone, starter
T_B = UUID("1112e9d4-f6b2-42bb-a217-5ba5dbe4b2a9")   # organizer, billing tenant (pro)
T_I = UUID("76a5e924-d6bc-43c4-9f16-54225384181b")   # linked institution
results = []
def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name + (f"  -> {detail}" if detail else ""))

async def expect_429(coro):
    try:
        await coro; return None
    except HTTPException as e:
        return e

async def main():
    from app.services.usage_service import check_and_increment
    from app.services.feature_service import enforce_static_limit, get_plan_limit
    from app.services.entitlement_service import resolve_plan
    from app.services import task_scheduler

    async with AsyncSessionLocal() as db:
        print("== limits in force ==")
        for label, t in (("starter", T_S), ("pro (via institution)", T_I)):
            lim = {k: await get_plan_limit(db, t, k) for k in ("events_per_month","invitations_per_month","invitations_per_event","guests_max","gates_per_event","designed_templates")}
            print(f"   {label:24s} {lim}")

        print("\n== S1: monthly limit reached (starter, events_per_month=1, already used 1) ==")
        e = await expect_429(check_and_increment(db, T_S, "events_per_month", 1)); await db.rollback()
        check("2nd event in the month is refused with HTTP 429", e is not None and e.status_code == 429, e.detail if e else "NOT REFUSED")

        print("\n== S2: static limits (live counts) ==")
        e = await expect_429(enforce_static_limit(db, T_S, "guests_max", 200, "الضيوف", requested=1))
        check("starter: guest #201 refused", e is not None and e.status_code == 429)
        e = await expect_429(enforce_static_limit(db, T_S, "guests_max", 199, "الضيوف", requested=1))
        check("starter: guest #200 allowed", e is None)
        e = await expect_429(enforce_static_limit(db, T_S, "invitations_per_event", 50, "الدعوات لكل حدث", requested=1))
        check("starter: invitation #51 in one event refused", e is not None and e.status_code == 429)
        e = await expect_429(enforce_static_limit(db, T_I, "invitations_per_event", 50, "الدعوات لكل حدث", requested=1))
        check("pro (institution workspace): invitation #51 allowed (limit 5000)", e is None)
        e = await expect_429(enforce_static_limit(db, T_I, "gates_per_event", 5, "البوابات", requested=1))
        check("pro: gate #6 refused (limit 5)", e is not None and e.status_code == 429)

        print("\n== S3: month rollover (counters are keyed by calendar month) ==")
        await db.execute(text("UPDATE usage_counters SET period_start = period_start - interval '1 month', period_end = (period_start - interval '1 month' + interval '1 month' - interval '1 day')::date WHERE tenant_id = :t"), {"t": str(T_S)})
        await db.commit()
        v = await check_and_increment(db, T_S, "events_per_month", 1); await db.commit()
        rows = (await db.execute(text("SELECT period_start::text, value FROM usage_counters WHERE tenant_id=:t AND key='events_per_month' ORDER BY 1"), {"t": str(T_S)})).all()
        check("new month starts a fresh counter (old month kept as history)", v == 1 and len(rows) == 2, str([tuple(r) for r in rows]))

        print("\n== S4: pro counter is shared by the linked workspaces ==")
        ok = True
        for i in range(10):
            try: await check_and_increment(db, T_I, "events_per_month", 1)
            except HTTPException: ok = False
        await db.commit()
        check("10 events allowed (limit 10) from the institution workspace", ok)
        e = await expect_429(check_and_increment(db, T_B, "events_per_month", 1)); await db.rollback()
        check("11th event refused even from the organizer workspace (shared billing counter)", e is not None and e.status_code == 429, e.detail if e else "")

        print("\n== S5: subscription expires ==")
        await db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE tenant_id=:t AND status='active'"), {"t": str(T_B)})
        await db.commit()
        plan = await resolve_plan(db, T_I)
        check("effective plan drops to starter immediately at read time (before any job runs)", plan["code"] == "starter", f"{plan['code']} / source={plan['source']}")
        before = (await db.execute(text("SELECT slug, plan FROM tenants WHERE id IN (:a,:b) ORDER BY slug"), {"a": str(T_B), "b": str(T_I)})).all()
        print("   tenants.plan cache before scheduler:", [tuple(r) for r in before])
        await task_scheduler._scan_subscriptions()
        sub = (await db.execute(text("SELECT status::text FROM subscriptions WHERE tenant_id=:t AND current_period_end < now() ORDER BY created_at DESC LIMIT 1"), {"t": str(T_B)})).scalar()
        after = (await db.execute(text("SELECT slug, plan FROM tenants WHERE id IN (:a,:b) ORDER BY slug"), {"a": str(T_B), "b": str(T_I)})).all()
        n = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.expired'"), {"t": str(T_B)})).scalar()
        check("scheduler marks the subscription canceled", sub == "canceled", sub)
        check("scheduler downgrades BOTH linked workspaces to starter", all(r[1] == "starter" for r in after), str([tuple(r) for r in after]))
        check("owner is notified (subscription.expired)", n == 1, f"{n} notification")
        e = await expect_429(check_and_increment(db, T_I, "events_per_month", 1)); await db.rollback()
        check("after expiry, new events are refused under starter limits", e is not None and e.status_code == 429)
        await task_scheduler._scan_subscriptions()
        n2 = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.expired'"), {"t": str(T_B)})).scalar()
        check("running the job again does not duplicate the notification", n2 == 1, f"{n2}")

        print("\n== S6: renewal reminders (7/3/1 days before the end) ==")
        plan_id = (await db.execute(text("SELECT id FROM plans WHERE code='pro'"))).scalar()
        await db.execute(text("""INSERT INTO subscriptions (tenant_id, plan_id, status, provider, current_period_start, current_period_end, cancel_at_period_end)
                                 VALUES (:t, :p, 'active', 'manual', now() - interval '27 days', now() + interval '3 days' - interval '1 hour', false)"""), {"t": str(T_B), "p": str(plan_id)})
        await db.commit()
        await task_scheduler._scan_subscriptions()
        r1 = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.renewal_reminder'"), {"t": str(T_B)})).scalar()
        await task_scheduler._scan_subscriptions()
        r2 = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.renewal_reminder'"), {"t": str(T_B)})).scalar()
        check("a reminder is emitted 3 days before the end", r1 == 1, f"{r1}")
        check("and is not repeated on the next scheduler tick", r2 == 1, f"{r2}")

    print(f"\nRESULT: {sum(results)}/{len(results)} checks passed")

asyncio.run(main())
