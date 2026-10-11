"""Behavioural check of the renewal flow against a CLONE of the database.

DESTRUCTIVE (edits subscriptions, custom plans, notifications).  Never run it
against production.  Covers: renewal window, staff queue suggestion, refusal to
cut paid days, extension from the current end, renewed/reminder/expired
notifications and e-mails (captured, not sent), reminders for custom plans.
Needs: PYTHONPATH=/app, DATABASE_URL pointing at the clone.  See RUNBOOK 6b.
"""
import asyncio, json
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import HTTPException, BackgroundTasks
from sqlalchemy import text
from starlette.requests import Request
from app.database import AsyncSessionLocal

T_B = UUID("1112e9d4-f6b2-42bb-a217-5ba5dbe4b2a9")      # billing tenant (pro)
results = []
def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name + (f"  -> {detail}" if detail else ""))

class Staff:
    email = "staff@example.test"
    id = None  # set from the first platform staff profile at start-up
def fake_request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1), "query_string": b""})

async def main():
    from app.routes import platform as plat
    from app.services import task_scheduler
    sent = []
    async with AsyncSessionLocal() as _db:
        Staff.id = (await _db.execute(text("SELECT id FROM profiles WHERE is_staff = true LIMIT 1"))).scalar_one()
    # capture e-mails instead of using SMTP
    from app.services import email_service as es
    for fn in ("send_subscription_expiring_email", "send_subscription_expired_email", "send_subscription_renewed_email", "send_subscription_upgraded_email"):
        setattr(es, fn, (lambda name: (lambda *a, **k: sent.append((name, a)) or True))(fn))
    plat.send_subscription_renewed_email = es.send_subscription_renewed_email
    plat.send_subscription_upgraded_email = es.send_subscription_upgraded_email

    async with AsyncSessionLocal() as db:
        # The restored clone has no auth.users rows (they live in the Auth service);
        # give the owners an address so the e-mail path can be exercised.
        await db.execute(text("SET LOCAL session_replication_role = replica"))  # skip the profile-creating trigger
        await db.execute(text("""INSERT INTO auth.users (id, email, aud, role)
                                 SELECT DISTINCT m.user_id, 'owner-' || substr(m.user_id::text, 1, 6) || '@example.test',
                                        'authenticated', 'authenticated'
                                 FROM memberships m ON CONFLICT (id) DO NOTHING"""))
        await db.commit()
        pro = (await db.execute(text("SELECT id FROM plans WHERE code='pro'"))).scalar()
        # a running Pro subscription that ends in 10 days
        end = datetime.now(timezone.utc) + timedelta(days=10)
        await db.execute(text("UPDATE subscriptions SET status='canceled' WHERE tenant_id=:t AND status IN ('active','trialing')"), {"t": str(T_B)})
        await db.execute(text("""INSERT INTO subscriptions (tenant_id, plan_id, status, provider, current_period_start, current_period_end, cancel_at_period_end)
                                 VALUES (:t,:p,'active','manual', now() - interval '20 days', :e, false)"""), {"t": str(T_B), "p": str(pro), "e": end})
        await db.commit()

        print("== renewal request window (tenant side) ==")
        from app.services.renewal import is_renewal_open
        check("10 days before the end the renewal window is open", is_renewal_open(end))
        check("45 days before the end it is not", not is_renewal_open(datetime.now(timezone.utc) + timedelta(days=45)))

        print("\n== staff queue shows the renewal ==")
        await db.execute(text("""INSERT INTO pending_subscriptions (tenant_id, plan_id, provider, provider_agreement_id, metadata)
                                 VALUES (:t,:p,'manual','manual_e2e', CAST(:m AS jsonb))"""),
                         {"t": str(T_B), "p": str(pro), "m": json.dumps({"plan_code": "pro", "plan_name": "Pro", "period": "monthly", "requested_by": str(Staff.id)})})
        await db.commit()
        rows = await plat.list_subscription_requests(user=Staff(), db=db)
        row = next(r for r in rows if str(r["tenant_id"]) == str(T_B))
        check("request is marked as a renewal with days left", row["is_renewal"] and row["days_left"] == 10, f"is_renewal={row['is_renewal']} days_left={row['days_left']}")
        suggested = datetime.fromisoformat(row["suggested_valid_until"])
        check("suggested end = current end + 30 days (remaining days kept)", abs((suggested - (end + timedelta(days=30))).total_seconds()) < 5, row["suggested_valid_until"][:10])

        print("\n== approval ==")
        from app.routes.platform import SubscriptionRequestApproval
        short = SubscriptionRequestApproval(payment_reference="REF-SHORT", valid_until=end + timedelta(days=1) - timedelta(days=2))
        try:
            await plat.approve_subscription_request(row["id"], short, fake_request(), BackgroundTasks(), Staff(), db); refused = None
        except HTTPException as e:
            refused = e
        await db.rollback()
        check("an end date that CUTS the paid period is refused (422)", refused is not None and refused.status_code == 422, (refused.detail[:60] if refused else "ACCEPTED"))

        ok_body = SubscriptionRequestApproval(payment_reference="REF-RENEW-1", valid_until=suggested)
        bg = BackgroundTasks()
        out = await plat.approve_subscription_request(row["id"], ok_body, fake_request(), bg, Staff(), db)
        check("renewal approved and flagged as renewal", out.get("renewal") is True, out["message"])
        cur = (await db.execute(text("SELECT status::text, current_period_end FROM subscriptions WHERE tenant_id=:t ORDER BY created_at DESC LIMIT 1"), {"t": str(T_B)})).mappings().first()
        check("new period ends 30 days after the OLD end (not 30 days from today)", abs((cur["current_period_end"] - (end + timedelta(days=30))).total_seconds()) < 5, str(cur["current_period_end"])[:10])
        n = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.renewed'"), {"t": str(T_B)})).scalar()
        check("owner notified with type subscription.renewed", n == 1, f"{n}")
        for task in bg.tasks:
            task.func(*task.args, **task.kwargs)
        check("renewal e-mail queued", any(n == "send_subscription_renewed_email" for n, _ in sent), str([n for n, _ in sent]))

        print("\n== reminders: standard + custom plan, e-mailed once ==")
        sent.clear()
        await db.execute(text("UPDATE subscriptions SET current_period_end = now() + interval '3 days' - interval '1 hour' WHERE tenant_id=:t AND status='active'"), {"t": str(T_B)})
        await db.commit()
        await task_scheduler._scan_subscriptions()
        await task_scheduler._scan_subscriptions()
        rem = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND type='subscription.renewal_reminder'"), {"t": str(T_B)})).scalar()
        mails = [n for n, _ in sent if n == "send_subscription_expiring_email"]
        check("one in-app reminder after two scheduler ticks", rem == 1, f"{rem}")
        check("one reminder e-mail (not repeated)", len(mails) == 1, f"{len(mails)}")

        # custom plan ending in 1 day
        await db.execute(text("UPDATE subscriptions SET status='canceled' WHERE tenant_id=:t AND status='active'"), {"t": str(T_B)})
        cols = "tenant_id, base_plan_id, status, activated_at, valid_until, name"
        try:
            await db.execute(text(f"""INSERT INTO custom_plans ({cols}) VALUES (:t,:p,'active', now() - interval '29 days', now() + interval '1 day' - interval '1 hour', 'خطة مخصصة')"""), {"t": str(T_B), "p": str(pro)})
            await db.commit()
            sent.clear()
            await task_scheduler._scan_subscriptions()
            c = (await db.execute(text("SELECT count(*) FROM notifications WHERE tenant_id=:t AND metadata->>'kind'='custom'"), {"t": str(T_B)})).scalar()
            check("custom plan gets a reminder too (1 day left)", c == 1, f"{c} (+{len(sent)} e-mail)")
        except Exception as exc:
            await db.rollback(); check("custom plan reminder", False, repr(exc)[:160])

        print("\n== expiry e-mail ==")
        await db.execute(text("UPDATE custom_plans SET status='canceled' WHERE tenant_id=:t"), {"t": str(T_B)})
        await db.execute(text("""INSERT INTO subscriptions (tenant_id, plan_id, status, provider, current_period_start, current_period_end)
                                 VALUES (:t,:p,'active','manual', now() - interval '31 days', now() - interval '1 hour')"""), {"t": str(T_B), "p": str(pro)})
        await db.commit(); sent.clear()
        await task_scheduler._scan_subscriptions(); await task_scheduler._scan_subscriptions()
        expired = [n for n, _ in sent if n == "send_subscription_expired_email"]
        check("expiry: downgrade notification + exactly one e-mail", len(expired) == 1, f"{len(expired)}")
    print(f"\nRESULT: {sum(results)}/{len(results)} checks passed")
asyncio.run(main())
