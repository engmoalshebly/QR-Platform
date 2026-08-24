"""
Seed the database via Supabase REST API (http://localhost:8000).
Creates plans, plan_limits, and subscriptions tables if missing,
then seeds the 5-tier professional plans data.

Plans:
  1. Starter   — مجانية (للتجربة)
  2. Basic     — 49 SAR/شهر
  3. Pro       — 149 SAR/شهر (الأكثر شعبية)
  4. Business  — 349 SAR/شهر
  5. Enterprise — تسعير مخصص
"""
import json
import os
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54821")
SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not SERVICE_ROLE_KEY:
    sys.exit("SUPABASE_SERVICE_ROLE_KEY env var is required (do not hardcode keys).")


def supabase_sql(sql: str) -> dict:
    """Execute SQL via Supabase's pg_query RPC (service role)."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/pg_query"
    body = json.dumps({"query": sql}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": resp.status, "data": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:500]}
    except Exception as e:
        return {"status": 0, "error": str(e)}


def supabase_rest_get(table: str) -> list:
    """GET from Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
    headers = {
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  GET /{table} error: {e.code} — {e.read().decode()[:200]}")
        return []
    except Exception as e:
        print(f"  GET /{table} error: {e}")
        return []


def supabase_rest_post(table: str, rows: list) -> dict:
    """POST to Supabase REST API (insert rows)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(rows).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "apikey": SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": resp.status, "data": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "error": e.read().decode()[:500]}
    except Exception as e:
        return {"status": 0, "error": str(e)}


# ══════════════════════════════════════════════
# PLAN DEFINITIONS
# ══════════════════════════════════════════════

PLANS = [
    {
        "code": "starter",
        "name": "Starter",
        "description": "للتجربة والاستخدام الشخصي",
        "subtitle": "ابدأ مجاناً",
        "price_monthly": 0,
        "price_yearly": 0,
        "currency": "YER",
        "badge_color": "#6b7280",
        "is_popular": False,
        "sort_order": 1,
        "features": [
            "حدث واحد شهرياً",
            "50 دعوة لكل حدث",
            "200 ضيف كحد أقصى",
            "بوابة تسجيل واحدة",
            "فريق عمل واحد (5 أعضاء)",
            "مستخدمان للوحة التحكم",
            "قوالب جاهزة فقط",
            "نموذج تسجيل واحد",
            "500 MB تخزين",
            "تقارير أساسية",
            "دعم عبر البريد الإلكتروني",
        ],
    },
    {
        "code": "basic",
        "name": "Basic",
        "description": "للأفراد ومنظمي الفعاليات الصغيرة",
        "subtitle": "الأكثر مرونة للبداية",
        "price_monthly": 14000,
        "price_yearly": 134000,
        "currency": "YER",
        "badge_color": "#3b82f6",
        "is_popular": False,
        "sort_order": 2,
        "features": [
            "3 أحداث شهرياً",
            "500 دعوة لكل حدث",
            "2,000 ضيف كحد أقصى",
            "بوابتين لكل حدث",
            "فريقين (10 أعضاء/فريق)",
            "5 مستخدمين للوحة التحكم",
            "5 قوالب مصممة",
            "نموذج تسجيل واحد",
            "2 GB تخزين",
            "1,500 دعوة شهرياً",
            "تقارير أساسية",
            "RSVP",
            "دعم عبر البريد الإلكتروني",
        ],
    },
    {
        "code": "pro",
        "name": "Pro",
        "description": "للفرق المتوسطة ومنظمي الفعاليات المحترفين",
        "subtitle": "الأكثر شعبية",
        "price_monthly": 35000,
        "price_yearly": 336000,
        "currency": "YER",
        "badge_color": "#8b5cf6",
        "is_popular": True,
        "sort_order": 3,
        "features": [
            "10 أحداث شهرياً",
            "5,000 دعوة لكل حدث",
            "10,000 ضيف كحد أقصى",
            "5 بوابات لكل حدث",
            "5 فرق (25 عضو/فريق)",
            "20 مستخدم للوحة التحكم",
            "قوالب مصممة غير محدودة",
            "نماذج تسجيل غير محدودة",
            "10 GB تخزين",
            "10,000 دعوة شهرياً",
            "تقارير متقدمة وتحليلات",
            "RSVP مع تخصيصات",
            "تصدير PDF وExcel",
            "تصميم بإحداثيات متقدم",
            "دعم ذو أولوية",
        ],
    },
    {
        "code": "business",
        "name": "Business",
        "description": "للشركات والمؤسسات متوسطة الحجم",
        "subtitle": "قوة بلا حدود",
        "price_monthly": 84000,
        "price_yearly": 805000,
        "currency": "YER",
        "badge_color": "#f59e0b",
        "is_popular": False,
        "sort_order": 4,
        "features": [
            "50 حدثاً شهرياً",
            "25,000 دعوة لكل حدث",
            "50,000 ضيف كحد أقصى",
            "15 بوابة لكل حدث",
            "15 فريق (50 عضو/فريق)",
            "75 مستخدماً للوحة التحكم",
            "قوالب مصممة غير محدودة",
            "نماذج تسجيل غير محدودة",
            "50 GB تخزين",
            "75,000 دعوة شهرياً",
            "تقارير متقدمة + لوحة تحليلات",
            "RSVP مع تخصيصات",
            "تصدير PDF وExcel",
            "تصميم بإحداثيات متقدم",
            "API Access",
            "Webhook Notifications",
            "مدير حساب مخصص",
            "دعم هاتفي + بريد + واتساب",
        ],
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "للمؤسسات الكبرى والجهات الحكومية",
        "subtitle": "حلول مخصصة بالكامل",
        "price_monthly": 0,
        "price_yearly": 0,
        "currency": "YER",
        "badge_color": "#059669",
        "is_popular": False,
        "sort_order": 5,
        "features": [
            "أحداث غير محدودة",
            "دعوات غير محدودة",
            "ضيوف غير محدود",
            "بوابات غير محدودة",
            "فرق غير محدودة",
            "مستخدمين غير محدود",
            "قوالب مصممة غير محدودة",
            "نموذج تسجيل واحد",
            "200 GB تخزين (قابل للزيادة)",
            "تقارير متقدمة + لوحة تحليلات مخصصة",
            "RSVP + تخصيص كامل",
            "API Access + Webhooks",
            "SSO (تسجيل دخول موحد)",
            "SLA (اتفاقية مستوى خدمة)",
            "White Label (علامة تجارية مخصصة)",
            "On-premise أو Cloud مخصص",
            "مدير حساب مخصص VIP",
            "دعم مخصص 24/7 بكل القنوات",
            "تدريب فريق العمل",
        ],
    },
]

# Limits per plan (-1 = unlimited)
PLAN_LIMITS = {
    "starter": [
        ("seats_max", 2, "none"),
        ("events_per_month", 1, "month"),
        ("invitations_per_event", 50, "none"),
        ("invitations_per_month", 100, "month"),
        ("teams_max", 1, "none"),
        ("team_members_per_team", 5, "none"),
        ("designed_templates", 1, "none"),
        ("gates_per_event", 1, "none"),
        ("guests_max", 200, "none"),
        ("registration_forms_max", 1, "none"),
        ("storage_mb", 500, "none"),
        ("messages_per_month", 100, "month"),
        ("ai_requests_per_month", 20, "month"),
    ],
    "basic": [
        ("seats_max", 5, "none"),
        ("events_per_month", 3, "month"),
        ("invitations_per_event", 500, "none"),
        ("invitations_per_month", 1500, "month"),
        ("teams_max", 2, "none"),
        ("team_members_per_team", 10, "none"),
        ("designed_templates", 3, "none"),
        ("gates_per_event", 2, "none"),
        ("guests_max", 2000, "none"),
        ("registration_forms_max", 1, "none"),
        ("storage_mb", 2000, "none"),
        ("messages_per_month", 500, "month"),
        ("ai_requests_per_month", 100, "month"),
    ],
    "pro": [
        ("seats_max", 20, "none"),
        ("events_per_month", 10, "month"),
        ("invitations_per_event", 5000, "none"),
        ("invitations_per_month", 10000, "month"),
        ("teams_max", 5, "none"),
        ("team_members_per_team", 25, "none"),
        ("designed_templates", 10, "none"),
        ("gates_per_event", 5, "none"),
        ("guests_max", 10000, "none"),
        ("registration_forms_max", -1, "none"),
        ("storage_mb", 10000, "none"),
        ("messages_per_month", 5000, "month"),
        ("ai_requests_per_month", 2000, "month"),
    ],
    "business": [
        ("seats_max", 75, "none"),
        ("events_per_month", 50, "month"),
        ("invitations_per_event", 25000, "none"),
        ("invitations_per_month", 75000, "month"),
        ("teams_max", 15, "none"),
        ("team_members_per_team", 50, "none"),
        ("designed_templates", 30, "none"),
        ("gates_per_event", 15, "none"),
        ("guests_max", 50000, "none"),
        ("registration_forms_max", -1, "none"),
        ("storage_mb", 50000, "none"),
        ("messages_per_month", -1, "month"),
        ("ai_requests_per_month", 10000, "month"),
    ],
    "enterprise": [
        ("seats_max", -1, "none"),
        ("events_per_month", -1, "month"),
        ("invitations_per_event", -1, "none"),
        ("invitations_per_month", -1, "month"),
        ("teams_max", -1, "none"),
        ("team_members_per_team", -1, "none"),
        ("designed_templates", -1, "none"),
        ("gates_per_event", -1, "none"),
        ("guests_max", -1, "none"),
        ("registration_forms_max", -1, "none"),
        ("storage_mb", 200000, "none"),
        ("messages_per_month", -1, "month"),
        ("ai_requests_per_month", -1, "month"),
    ],
}


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Qentry Platform — Professional Plans Seed Script       ║")
    print("║  5 Tiers: Starter → Basic → Pro → Business → Enterprise ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  🌐 Supabase: {SUPABASE_URL}\n")

    # ── 1. Check/ensure plans table columns ──
    print("1. Ensuring plans table schema...")
    alter_sql = """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='plans' AND column_name='badge_color') THEN
            ALTER TABLE public.plans ADD COLUMN badge_color TEXT DEFAULT '#6b7280';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='plans' AND column_name='subtitle') THEN
            ALTER TABLE public.plans ADD COLUMN subtitle TEXT DEFAULT '';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='plans' AND column_name='is_popular') THEN
            ALTER TABLE public.plans ADD COLUMN is_popular BOOLEAN DEFAULT false;
        END IF;
    END $$;
    """
    supabase_sql(alter_sql)
    print("  ✅ Schema ensured")

    # ── 2. Upsert plans ──
    print("\n2. Upserting plans via REST API...")
    result = supabase_rest_post("plans", PLANS)
    if result.get("status") in (200, 201):
        data = result.get("data", [])
        print(f"  ✅ Plans upserted: {[p.get('code') for p in data]}")
    else:
        print(f"  ❌ Failed: {result}")
        print("  💡 Run migration_v11_professional_plans.sql manually.")
        return

    # ── 3. Seed limits ──
    print("\n3. Seeding plan limits...")
    plans = supabase_rest_get("plans")
    plan_map = {p["code"]: p["id"] for p in plans}

    for plan_code, limits in PLAN_LIMITS.items():
        plan_id = plan_map.get(plan_code)
        if not plan_id:
            print(f"  ⚠️  Plan '{plan_code}' not found, skipping limits")
            continue

        limit_rows = [
            {"plan_id": plan_id, "key": key, "value": value, "period": period}
            for key, value, period in limits
        ]
        res = supabase_rest_post("plan_limits", limit_rows)
        if res.get("status") in (200, 201):
            print(f"  ✅ {plan_code:12s} — {len(limit_rows)} limits")
        else:
            print(f"  ⚠️  {plan_code:12s} — {res.get('error', 'unknown')[:80]}")

    # ── 4. Verify ──
    print("\n4. Verification:")
    plans = supabase_rest_get("plans")
    print(f"\n  {'Code':12s} {'Name':12s} {'Monthly':>10s} {'Yearly':>10s} {'Currency':>8s} {'Popular':>8s}")
    print(f"  {'─'*12} {'─'*12} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")
    for p in sorted(plans, key=lambda x: x.get("sort_order", 0)):
        monthly = p.get("price_monthly", 0)
        yearly = p.get("price_yearly", 0)
        popular = "⭐" if p.get("is_popular") else ""
        price_str = f"{monthly:,.0f}" if monthly > 0 else "مجانية"
        yearly_str = f"{yearly:,.0f}" if yearly > 0 else "—"
        code = p.get("code", "?")
        if code == "enterprise":
            price_str = "تسعير مخصص"
            yearly_str = "تسعير مخصص"
        print(f"  {code:12s} {p.get('name', '?'):12s} {price_str:>10s} {yearly_str:>10s} {p.get('currency', '?'):>8s} {popular:>8s}")

    limits_count = supabase_rest_get("plan_limits")
    print(f"\n  📊 Total plans: {len(plans)}")
    print(f"  📊 Total limits: {len(limits_count)}")
    print("  🎉 Professional plans system ready!")


if __name__ == "__main__":
    main()
