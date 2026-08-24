# 🚀 دليل تشغيل واختبار بوابة الدفع الموحدة (Link Gateway Service)

هذا الدليل يشرح خطوة بخطوة كيفية إعداد وتشغيل الخدمة واختبار كافة مسارات الدفع (Full Payment Lifecycle) عبر **cURL** أو **Postman**.

---

## 📋 المتطلبات الأساسية

1. **Node.js**: الإصدار 18 أو أحدث (`node -v`).
2. **Supabase Account**: مشروع مجاني أو مدفوع على [supabase.com](https://supabase.com).
3. **Redis** *(اختياري للبيئة المحلية - الخدمة تعمل تلقائياً حتى بدون Redis حيث تلجأ للمصادقة المباشرة)*.

---

## 🛠️ الخطوة 1: إعداد قاعدة البيانات في Supabase

1. ادخل إلى لوحة تحكم مشروعك في [Supabase Dashboard](https://app.supabase.com).
2. من القائمة الجانبية، افتح **SQL Editor**.
3. افتح ملف الميجريشن:
   [`src/database/migrations/001_initial_schema.sql`](./src/database/migrations/001_initial_schema.sql)
4. انسخ المحتوى والصقه في الـ SQL Editor واضغط **Run**.
5. ستنشأ الجداول التالية تلقائياً:
   - `payments` (جدول سجلات الدفع)
   - `gateway_transactions` (سجل اتصالات البوابة)
   - `gateway_providers` (كاش المحافظ والبنوك)
   - `payment_audit_log` (سجل تتبع الحالات)

---

## ⚙️ الخطوة 2: ضبط المتغيرات البيئية (`.env`)

1. داخل مجلد المشروع `link-gateway-service`، أنشئ ملف باسم `.env`:
   ```bash
   cp .env.example .env
   ```
2. افتح ملف `.env` واملأ القيم التالية:

```env
# منفذ تشغيل الخدمة
PORT=3000
NODE_ENV=development

# ──────────────────────────────────────────────
# إعدادات Supabase (احصل عليها من Project Settings -> API)
# ──────────────────────────────────────────────
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ──────────────────────────────────────────────
# إعدادات بوابة Link Unified Gateway (Sandbox)
# ──────────────────────────────────────────────
LINK_GATEWAY_BASE_URL=https://payment-test.tharwatt.com
LINK_API_PROFILE=tharwatt
LINK_STATUS_PATH=/replace-with-link-status-endpoint
LINK_CLIENT_ID=halali-app
LINK_CLIENT_SECRET=replace-with-link-issued-secret

# بيانات التاجر الخاص بك في البوابة
LINK_MERCHANT_ORG_CODE=Easy
LINK_MERCHANT_ACCOUNT_TYPE=MerchantId
LINK_MERCHANT_ACCOUNT_ID=replace-with-link-merchant-id
LINK_FIXED_FEE_YER=0
LINK_FIXED_COMMISSION_YER=0

# ──────────────────────────────────────────────
# مفتاح أمان الـ APIs الداخلية (X-API-Key)
# ──────────────────────────────────────────────
API_KEY=test-secret-key-2026
```

---

## 🏃 الخطوة 3: تشغيل الخدمة

افتح الـ Terminal داخل مجلد `link-gateway-service`:

```bash
# تشغيل السيرفر في وضع التطوير (Hot-reload)
npm run start:dev
```

ستظهر لك رسالة الإقلاع:
```text
══════════════════════════════════════════
  🚀 Link Gateway Service is running
  📡 Port: 3000
  🌍 Environment: development
  🔗 Health: http://localhost:3000/health
  📚 API Base: http://localhost:3000/api/v1
══════════════════════════════════════════
```

---

## 🧪 الخطوة 4: اختبار مسار الدفع الكامل (End-to-End Testing)

يمكنك تنفيذ هذه الأوامر عبر أي Terminal (PowerShell / Bash) أو استيراد ملف Postman المرفق.

### 1️⃣ فحص جاهزية السيرفر (Health Check)
```bash
curl -X GET http://localhost:3000/health
```
**الاستجابة المتوقعة:**
```json
{
  "status": "ok",
  "service": "link-gateway-service",
  "timestamp": "2026-08-20T10:15:00.000Z"
}
```

---

### 2️⃣ جلب المحافظ الإلكترونية المتاحة
```bash
curl -X GET http://localhost:3000/api/v1/payments/providers \
  -H "X-API-Key: test-secret-key-2026"
```
**الاستجابة المتوقعة:**
```json
{
  "success": true,
  "providers": [
    {
      "code": "Floosak",
      "name": "محفظة فلوسك",
      "nameEn": "Floosak GateWay",
      "logoUrl": "https://apimgt-dev.tharwatt.com:56000/logos/Floosak.jpg",
      "sector": "Wallets",
      "isActive": true
    },
    {
      "code": "Easy",
      "name": "محفظة ايزي",
      "nameEn": "EasyWallet",
      "logoUrl": "https://apimgt-dev.tharwatt.com:56000/logos/EasyWallet.png",
      "sector": "Wallets",
      "isActive": true
    },
    {
      "code": "Jaib",
      "name": "محفظة جيب",
      "nameEn": "Jaib Wallet",
      "logoUrl": "https://apimgt-dev.tharwatt.com:56000/logos/Jaib.png",
      "sector": "Wallets",
      "isActive": true
    }
  ]
}
```

---

### 3️⃣ حساب رسوم العملية قبل الخصم
```bash
curl -X POST http://localhost:3000/api/v1/payments/fees \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-secret-key-2026" \
  -d '{
    "providerCode": "Floosak",
    "amount": 2000,
    "currency": "YER"
  }'
```
**الاستجابة المتوقعة:**
```json
{
  "success": true,
  "amount": 2000,
  "fees": 40,
  "commission": 0,
  "totalAmount": 2040,
  "currency": "YER",
  "feeDetails": {
    "sourceFees": 0,
    "switchFees": 0,
    "gwFees": 40,
    "beneficiaryFees": 0
  }
}
```

---

### 4️⃣ بدء عملية الدفع (Initiate Payment)
يقوم تطبيقك بطلب الدفع برقم محفظة العميل:
```bash
curl -X POST http://localhost:3000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-secret-key-2026" \
  -d '{
    "orderId": "INV-1005",
    "appId": "my-shop",
    "paymentMethod": "WALLET_OTP",
    "providerCode": "Floosak",
    "walletNumber": "773391212",
    "amount": 2000,
    "currency": "YER"
  }'
```
**الاستجابة المتوقعة:**
```json
{
  "success": true,
  "paymentId": "e82bcb60-d1e6-4472-9929-1adb31fcfee7",
  "status": "OTP_REQUIRED",
  "fees": 40,
  "commission": 0,
  "totalAmount": 2040,
  "expiresAt": "2026-08-20T13:15:00.000Z"
}
```
*(احفظ قيمة `paymentId` للخطوة التالية)*

---

### 5️⃣ تأكيد الدفع برمز التحقق (Confirm OTP)
المستخدم يدخل الرمز الذي وصله في محفظته:
```bash
curl -X POST http://localhost:3000/api/v1/payments/e82bcb60-d1e6-4472-9929-1adb31fcfee7/confirm \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-secret-key-2026" \
  -d '{
    "otp": "65454"
  }'
```
**الاستجابة المتوقعة عند النجاح:**
```json
{
  "success": true,
  "paymentId": "e82bcb60-d1e6-4472-9929-1adb31fcfee7",
  "status": "SUCCESS",
  "transactionId": "87839846537",
  "amount": 2000,
  "paidAt": "2026-08-20T10:16:30.000Z"
}
```

---

### 6️⃣ الاستعلام عن حالة الدفعة من منصتك
```bash
curl -X GET http://localhost:3000/api/v1/payments/e82bcb60-d1e6-4472-9929-1adb31fcfee7 \
  -H "X-API-Key: test-secret-key-2026"
```
**الاستجابة المتوقعة:**
```json
{
  "paymentId": "e82bcb60-d1e6-4472-9929-1adb31fcfee7",
  "orderId": "INV-1005",
  "appId": "my-shop",
  "status": "SUCCESS",
  "paymentMethod": "WALLET_OTP",
  "providerCode": "Floosak",
  "amount": 2000,
  "fees": 40,
  "totalAmount": 2040,
  "currency": "YER",
  "paidAt": "2026-08-20T10:16:30.000Z"
}
```

---

### 7️⃣ الاستعلام عن رصيد حساب التاجر (Merchant Balance)
```bash
curl -X GET "http://localhost:3000/api/v1/merchant/balance?currency=YER" \
  -H "X-API-Key: test-secret-key-2026"
```

---

### 8️⃣ إصدار كود دفع / QR Code (Vouchers)
```bash
curl -X POST http://localhost:3000/api/v1/vouchers/issue \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-secret-key-2026" \
  -d '{
    "orderId": "INV-2001",
    "providerCode": "Easy",
    "walletNumber": "778090809",
    "amount": 2000,
    "currency": "YER"
  }'
```

---

### 9️⃣ استعلام المطابقة والتقارير المالية (Reconciliation)
```bash
curl -X GET "http://localhost:3000/api/v1/reconciliation/transactions?startDate=2026/08/01&endDate=2026/08/20&status=success" \
  -H "X-API-Key: test-secret-key-2026"
```

---

## 🎯 نصائح استكشاف الأخطاء (Troubleshooting)

1. **خطأ `Missing or invalid API key`**:
   - تأكد من إرسال Header باسم `X-API-Key` بنفس القيمة المحددة في `.env`.
2. **خطأ `Authentication failed` مع Link**:
   - تأكد من صحة `LINK_CLIENT_ID` و `LINK_CLIENT_SECRET` وعنوان `LINK_GATEWAY_BASE_URL`.
3. **العمليات المعلقة `PENDING`**:
   - الـ `StatusWorkerService` يقوم تلقائياً كل 30 ثانية بفحص العمليات وتحديثها فور اكتمالها في البوابة دون أي تدخل يدوي.
