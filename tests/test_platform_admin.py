"""Test Platform Admin API endpoints including modification endpoints"""
import sys, json, urllib.request, urllib.error
from datetime import datetime, timedelta
import jwt

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8021/api/v1"
JWT_SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
USER_ID = "9d32fe8c-50a6-4bc0-9b0b-278bdde11109"

# Generate JWT locally using secret key
def generate_token():
    payload = {
        "sub": USER_ID,
        "email": "owner@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(datetime.utcnow().timestamp()),
        "exp": int((datetime.utcnow() + timedelta(days=1)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def api_call(method, path, body=None, token=None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"} if body else {},
        method=method
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except:
            return e.code, {"error": e.read().decode()}

print("=" * 60)
print("  Platform Admin API Test (Advanced)")
print("=" * 60)

token = generate_token()
print(f"Generated admin token: {token[:20]}...")

# 1. Get plans and addons
print("\n1. GET /platform/plans-overview...")
code, data = api_call("GET", "/platform/plans-overview", token=token)
print(f"   Status: {code}")
if code == 200:
    plans = data.get("plans", [])
    addons = data.get("addons", [])
    print(f"   Found {len(plans)} plans and {len(addons)} addons.")
    
    if plans:
        plan = plans[0]
        plan_id = plan["id"]
        print(f"   Testing modifications on plan: {plan['name']} (ID: {plan_id})")
        
        # 2. Update Plan
        print(f"\n2. PATCH /platform/plans/{plan_id}...")
        p_code, p_res = api_call("PATCH", f"/platform/plans/{plan_id}", {"subtitle": "عنوان فرعي تجريبي جديد"}, token=token)
        print(f"   Status: {p_code} — Response: {p_res}")
        
        # Restore plan subtitle
        api_call("PATCH", f"/platform/plans/{plan_id}", {"subtitle": plan.get("subtitle") or ""}, token=token)
        
        # 3. Get Plan Limits
        print(f"\n3. GET /platform/plans/{plan_id}/limits...")
        l_code, l_res = api_call("GET", f"/platform/plans/{plan_id}/limits", token=token)
        print(f"   Status: {l_code}")
        if l_code == 200:
            print(f"   Limits count: {len(l_res)}")
            if l_res:
                print(f"   Sample limit: {l_res[0]}")
                
                # 4. Update Plan Limits
                print(f"\n4. PUT /platform/plans/{plan_id}/limits...")
                # let's duplicate the list of limits to save them back
                lp_code, lp_res = api_call("PUT", f"/platform/plans/{plan_id}/limits", l_res, token=token)
                print(f"   Status: {lp_code} — Response: {lp_res}")
                
        # 5. Update Addon Price
        if addons:
            addon = addons[0]
            addon_id = addon["id"]
            print(f"\n5. PATCH /platform/addons/{addon_id}...")
            a_code, a_res = api_call("PATCH", f"/platform/addons/{addon_id}", {"price_per_unit": float(addon["price_per_unit"]) + 1.0}, token=token)
            print(f"   Status: {a_code} — Response: {a_res}")
            
            # Restore addon price
            api_call("PATCH", f"/platform/addons/{addon_id}", {"price_per_unit": float(addon["price_per_unit"])}, token=token)
            print("   Restored original addon price.")

print(f"\n{'='*60}")
print("  Test Complete!")
print(f"{'='*60}")
