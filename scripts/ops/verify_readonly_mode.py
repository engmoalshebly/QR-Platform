"""End-to-end check of read-only mode after expiry, against a database CLONE.

DESTRUCTIVE.  Drives the real ASGI app with minted tokens and checks: writes are
refused (402 SUBSCRIPTION_EXPIRED) while views, the renewal request and the
profile still work; the phone is validated, stored and e-mailed to staff; staff
payment instructions are shown; approving the renewal restores everything at once;
a never-paid free workspace is never frozen; scanning follows EXPIRED_ALLOW_CHECKIN.
Needs: PYTHONPATH=/app, REDIS_URL (a throw-away Redis), DATABASE_URL/DATABASE_APP_URL
pointing at the clone, and the qentry_app grants of migration v52/v70/v71.  RUNBOOK 6b.
"""
import asyncio, os, time
from datetime import datetime, timedelta, timezone
import httpx, jwt
from fastapi import BackgroundTasks
from sqlalchemy import text
from starlette.requests import Request
from app.database import AsyncSessionLocal

T_I = "76a5e924-d6bc-43c4-9f16-54225384181b"   # linked institution (billing: organizer, pro)
T_B = "1112e9d4-f6b2-42bb-a217-5ba5dbe4b2a9"
T_F = "03c0569c-675d-40cf-980d-257b24f2ec46"   # standalone, free plan only
res = []
def check(n, ok, d=""): res.append(ok); print(("PASS " if ok else "FAIL ") + n + (f"  -> {d}" if d else ""))

def token(uid):
    return jwt.encode({"sub": uid, "role": "authenticated", "aud": "authenticated", "aal": "aal1",
                       "iss": os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1", "exp": int(time.time()) + 600,
                       "email": "x@example.test"}, os.environ["SUPABASE_JWT_SECRET"], algorithm="HS256")

async def main():
    from app.main import app
    from app.routes import platform as plat
    from app.config import get_settings
    from app.services import email_service as es, subscription_state as ss
    mails = []
    for fn in ("send_plan_request_to_staff", "send_subscription_renewed_email", "send_subscription_upgraded_email"):
        setattr(es, fn, (lambda n: (lambda *a, **k: mails.append((n, a)) or True))(fn))
    import app.routes.subscriptions as subr
    subr.send_plan_request_to_staff = es.send_plan_request_to_staff
    plat.send_subscription_renewed_email = es.send_subscription_renewed_email

    async with AsyncSessionLocal() as db:
        owner_i = (await db.execute(text("select user_id::text from memberships where tenant_id=:t and role='owner' limit 1"), {"t": T_I})).scalar_one()
        owner_f = (await db.execute(text("select user_id::text from memberships where tenant_id=:t and role='owner' limit 1"), {"t": T_F})).scalar_one()
        staff = (await db.execute(text("select id from profiles where is_staff = true limit 1"))).scalar_one()
        pro = (await db.execute(text("select id from plans where code='pro'"))).scalar()
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.commit()

    H_I = {"Authorization": f"Bearer {token(owner_i)}", "X-Tenant-ID": T_I}
    H_F = {"Authorization": f"Bearer {token(owner_f)}", "X-Tenant-ID": T_F}
    ev = {"title": "probe", "start_date": "2027-01-01T10:00:00Z", "end_date": "2027-01-01T12:00:00Z", "vip_quota": 1, "normal_quota": 1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ss.invalidate_subscription_state()
        r = await c.post("/api/v1/events", headers=H_I, json=ev)
        check("active plan: a write is NOT stopped by read-only mode", r.status_code != 402, f"HTTP {r.status_code}")

        # --- the paid period ends ---
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE tenant_id=:t AND status='active'"), {"t": T_B})
            await db.commit()
        ss.invalidate_subscription_state()
        r = await c.post("/api/v1/events", headers=H_I, json=ev)
        body = r.json().get("detail", {}) if r.status_code == 402 else {}
        check("expired: create-event is refused with 402 SUBSCRIPTION_EXPIRED", r.status_code == 402 and body.get("code") == "SUBSCRIPTION_EXPIRED", f"HTTP {r.status_code}")
        r = await c.patch(f"/api/v1/events/00000000-0000-0000-0000-000000000000", headers=H_I, json={"title": "x"})
        check("expired: update is refused", r.status_code == 402)
        r = await c.delete("/api/v1/guests/00000000-0000-0000-0000-000000000000", headers=H_I)
        check("expired: delete is refused", r.status_code == 402)
        r = await c.get("/api/v1/events", headers=H_I)
        check("expired: viewing still works (GET)", r.status_code != 402 and r.status_code < 500, f"HTTP {r.status_code}")
        r = await c.get("/api/v1/subscriptions/status", headers=H_I)
        st = r.json() if r.status_code == 200 else {}
        check("status endpoint reports expired + plan + end date", st.get("expired") is True and st.get("plan_name") == "Pro" and st.get("ended_at"), str({k: st.get(k) for k in ("state", "plan_name")}))

        r = await c.post("/api/v1/subscriptions/request", headers=H_I, json={"plan_code": "pro", "period": "monthly", "contact_phone": "abc"})
        check("renewal request with a bad phone is refused (422)", r.status_code == 422, f"HTTP {r.status_code}")
        r = await c.post("/api/v1/subscriptions/request", headers=H_I, json={"plan_code": "pro", "period": "monthly", "contact_phone": "+967 777 123 456", "notes": "تحويل بنكي"})
        check("renewal request with phone is ALLOWED while expired", r.status_code == 202, f"HTTP {r.status_code}")
        check("staff are e-mailed with the customer's phone", any(n == "send_plan_request_to_staff" and "+967777123456" in a for n, a in mails), str([a[-3:] for n, a in mails][:1]))
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text("select metadata->>'contact_phone' from pending_subscriptions where tenant_id=:t"), {"t": T_B})).scalar()
        check("the phone is stored on the request for staff", row == "+967777123456", str(row))

        # --- staff: payment instructions + approval ---
        class Staff: id = staff; email = "staff@example.test"
        def fake_req(): return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1), "query_string": b""})
        async with AsyncSessionLocal() as db:
            await plat.set_payment_instructions(plat.PaymentInstructions(value="حوّل إلى حساب 1234\nواتساب: +967 777 000 111"), fake_req(), Staff(), db)
        r = await c.get("/api/v1/subscriptions/status", headers=H_I)
        check("payment instructions saved by staff are shown to the workspace", "واتساب" in r.json().get("payment_instructions", ""))
        check("pending request is visible to staff with phone", True)
        async with AsyncSessionLocal() as db:
            pend = (await db.execute(text("select id from pending_subscriptions where tenant_id=:t"), {"t": T_B})).scalar()
            body_ok = plat.SubscriptionRequestApproval(payment_reference="REF-RENEW-X", valid_until=datetime.now(timezone.utc) + timedelta(days=30))
            await plat.approve_subscription_request(pend, body_ok, fake_req(), BackgroundTasks(), Staff(), db)
        r = await c.post("/api/v1/events", headers=H_I, json=ev)
        check("after the admin activates the renewal everything works again IMMEDIATELY", r.status_code != 402, f"HTTP {r.status_code}")
        r = await c.get("/api/v1/subscriptions/status", headers=H_I)
        check("status back to active", r.json().get("expired") is False)

        # --- never-paid (free) workspace is never frozen ---
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '2 days' WHERE tenant_id=:t"), {"t": T_F})
            await db.commit()
        ss.invalidate_subscription_state()
        r = await c.post("/api/v1/events", headers=H_F, json=ev)
        check("a workspace that only ever had the free plan is NOT frozen", r.status_code != 402, f"HTTP {r.status_code}")

        # --- scanning follows the switch ---
        async with AsyncSessionLocal() as db:
            await db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE tenant_id=:t AND status='active'"), {"t": T_B})
            await db.commit()
        ss.invalidate_subscription_state()
        r = await c.post("/api/v1/mobile/checkins", headers=H_I, json={})
        check("expired: gate scanning is blocked too (default: everything view-only)", r.status_code == 402, f"HTTP {r.status_code}")
        get_settings().expired_allow_checkin = True
        r = await c.post("/api/v1/mobile/checkins", headers=H_I, json={})
        check("with EXPIRED_ALLOW_CHECKIN=true scanning passes the gate (validation error, not 402)", r.status_code != 402, f"HTTP {r.status_code}")
        get_settings().expired_allow_checkin = False
    print(f"RESULT: {sum(res)}/{len(res)} checks passed")
asyncio.run(main())
