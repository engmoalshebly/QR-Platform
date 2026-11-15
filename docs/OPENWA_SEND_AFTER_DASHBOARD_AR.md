# استخدام API بعد ربط الرقم من الداشبورد

هذا الدليل مخصص للحالة التالية: أنشأت جلسة من لوحة OpenWA، ومسحت QR من هاتف الرقم المرسل، وأصبحت الجلسة **Connected**. لا تحتاج إنشاء جلسة جديدة عبر API؛ تستخدم معرّف الجلسة الموجودة.

**الداشبورد:** https://notify.prideidea.com/dashboard

**عنوان API:** `https://notify.prideidea.com/api`

## 1. انسخ معرّف الجلسة

من **Sessions** افتح تفاصيل الجلسة المرتبطة وانسخ **Session ID**. المعرف UUID وليس اسم الجلسة أو رقم الهاتف. تحقق من الرقم المعروض قبل اعتماده للإرسال.

مثال تمثيلي:

```text
اسم الجلسة: orders-sender
Session ID: 11111111-1111-4111-8111-111111111111
```

## 2. جهز مفتاحاً خاصاً بهذه الجلسة

تسجيل الدخول إلى الداشبورد لا ينشئ تلقائياً مفتاحاً مقيداً بالجلسة. أصدر مفتاحاً من خادم الإدارة، ثم أعط النظام الثاني هذا المفتاح ومعرّف الجلسة.

يمكن إنشاء مفتاح operator من صفحة **API Keys**، لكن نافذتها الحالية لا تعرض حقل تقييد الجلسة. الطلب التالي ينشئ المفتاح ويقيده بالجلسة صراحة. يحتاج `curl` و`jq`.

حمّل المتغيرات التالية من مخزن أسرار أو ملف بيئة محمي على الخادم:

```dotenv
OPENWA_API_BASE=https://notify.prideidea.com/api
OPENWA_ADMIN_KEY=<مفتاح إدارة OpenWA>
OPENWA_SESSION_ID=<Session ID المنسوخ من الداشبورد>
```

مفتاح إدارة اللوحة موجود في ملف `/home/alrazi/.qentry/openwa-dashboard-admin.json` تحت `api_key`. استخدمه لإصدار مفتاح النظام؛ لا ترسل مفتاح الإدارة إلى النظام الثاني أو المتصفح.

```bash
umask 077
curl --fail-with-body --silent --show-error \
  "$OPENWA_API_BASE/auth/api-keys" \
  -H "X-API-Key: $OPENWA_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg sid "$OPENWA_SESSION_ID" \
    '{name:"orders-system-sender",role:"operator",allowedSessions:[$sid]}')" \
  > openwa-system-key.json
```

الاستجابة تحتوي، ضمن حقول أخرى:

```json
{
  "id": "معرف-المفتاح",
  "role": "operator",
  "allowedSessions": ["معرف-جلستك"],
  "apiKey": "المفتاح-الجديد-الذي-سيستخدمه-النظام"
}
```

احفظ `apiKey` في إعدادات خادم النظام الثاني باسم `OPENWA_SEND_KEY`. يظهر المفتاح الكامل عند الإنشاء فقط. احفظ `id` أيضاً لتتمكن من إلغائه لاحقاً. لا تشارك ملف المفاتيح أو تضفه إلى Git.

> هذا قيد على مسارات الجلسة، وليس عزلاً كاملاً بين مؤسسات مختلفة في جميع مسارات OpenWA العامة. اجعل خادم نظامك وسيطاً موثوقاً، ولا تكشف مفتاح المزود للمستخدمين النهائيين.

## 3. ضع بيانات الربط في النظام الثاني

خادم النظام الثاني يحتاج ثلاث قيم فقط لاستخدام جلسة جاهزة:

```dotenv
OPENWA_API_BASE=https://notify.prideidea.com/api
OPENWA_SESSION_ID=<Session ID المنسوخ من الداشبورد>
OPENWA_SEND_KEY=<apiKey الصادر في الخطوة السابقة>
```

يُضاف مفتاح الإرسال في رأس `X-API-Key` لكل طلب. رقم المرسل يحدده **معرّف الجلسة في المسار**؛ لا تضف `from` ولا تستبدل المعرف برقم الهاتف.

## 4. تحقق من الاتصال

```bash
curl --fail-with-body --silent --show-error \
  "$OPENWA_API_BASE/sessions/$OPENWA_SESSION_ID" \
  -H "X-API-Key: $OPENWA_SEND_KEY"
```

مثال استجابة مختصر:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "name": "orders-sender",
  "status": "ready",
  "phone": "رقم-المرسل-المرتبط"
}
```

اسمح بالإرسال عندما تكون `status` مساوية لـ`ready`، وتحقق أن `phone` يطابق رقم المرسل الذي ربطته. إذا كان الربط قد اكتمل فلا تحتاج طلب QR مجدداً.

## 5. أرسل رسالة عبر API

الطلب:

```http
POST https://notify.prideidea.com/api/sessions/SESSION_ID/messages/send-text
X-API-Key: YOUR_SESSION_API_KEY
Content-Type: application/json

{
  "chatId": "RECIPIENT_NUMBER@c.us",
  "text": "تم تأكيد طلبك بنجاح."
}
```

استبدل `RECIPIENT_NUMBER` برقم **المستلم** بالصيغة الدولية: رمز البلد ثم الرقم، دون `+` أو مسافات. لا تغير اللاحقة `@c.us`. النص غير فارغ وبحد أقصى 4096 حرفاً.

مثال `curl` — يرسل رسالة فعلية عند تنفيذه بقيم صحيحة:

```bash
# حمّل RECIPIENT_NUMBER من إعداد اختبار مقصود لرقم مصرح بمراسلته.
curl --fail-with-body --silent --show-error \
  "$OPENWA_API_BASE/sessions/$OPENWA_SESSION_ID/messages/send-text" \
  -H "X-API-Key: $OPENWA_SEND_KEY" \
  -H 'Content-Type: application/json' \
  --data "$(jq -n --arg phone "$RECIPIENT_NUMBER" \
    --arg message 'تم تأكيد طلبك بنجاح.' \
    '{chatId:($phone+"@c.us"),text:$message}')"
```

الاستجابة الناجحة تتضمن:

```json
{"messageId":"معرف-الرسالة-لدى-المزود","timestamp":1792470000}
```

احفظ `messageId` مع معرّف العملية التجارية. نجاح الطلب يعني أن المزود أعاد نتيجة إرسال؛ تأكيد التسليم والقراءة يحتاج إيصالات Webhook.

## 6. مثال ربط Node.js

ينفذ على **خادم النظام الثاني**، وليس في المتصفح. يستخدم `fetch` المتاح في إصدارات Node الحديثة، ولا ينفذ إعادة إرسال تلقائية.

```javascript
const base = process.env.OPENWA_API_BASE.replace(/\/$/, '');
const sessionId = process.env.OPENWA_SESSION_ID;
const headers = {
  'X-API-Key': process.env.OPENWA_SEND_KEY,
  'Content-Type': 'application/json',
};

async function sendWhatsApp(to, text) {
  if (!/^[1-9][0-9]{7,14}$/.test(to)) {
    throw new Error('استخدم رقم مستلم دولياً بالأرقام فقط');
  }
  if (typeof text !== 'string' || !text.trim() || text.length > 4096) {
    throw new Error('النص مطلوب وبحد أقصى 4096 حرفاً');
  }

  const state = await fetch(`${base}/sessions/${sessionId}`, {
    headers, signal: AbortSignal.timeout(15000),
  });
  if (!state.ok) throw new Error(`فشل فحص الاتصال: HTTP ${state.status}`);
  const session = await state.json();
  if (session.status !== 'ready') throw new Error('رقم WhatsApp غير متصل');

  let response;
  try {
    response = await fetch(`${base}/sessions/${sessionId}/messages/send-text`, {
      method: 'POST', headers,
      body: JSON.stringify({ chatId: `${to}@c.us`, text }),
      signal: AbortSignal.timeout(30000),
    });
  } catch {
    throw new Error('نتيجة الإرسال غير محسومة؛ راجع قبل إعادة الإرسال');
  }
  if (!response.ok) {
    throw new Error(`تعذر تأكيد الإرسال: HTTP ${response.status}؛ راجع النتيجة قبل التكرار`);
  }
  let result;
  try { result = await response.json(); }
  catch { throw new Error('رد الإرسال غير قابل للقراءة؛ راجع قبل التكرار'); }
  if (!result.messageId) throw new Error('معرف الرسالة غير موجود؛ راجع قبل التكرار');
  return result;
}

// استدعها من منطق العمل بعد تحديد رقم مصرح بمراسلته:
// const result = await sendWhatsApp(recipientNumber, 'تم تأكيد طلبك.');
// احفظ result.messageId في قاعدة بياناتك.
```

افحص أيضاً رقم المرسل أثناء إعداد الربط واحفظه مع الجلسة؛ مثال الدالة يفحص الجاهزية ولا يطبق صلاحيات مستخدمي نظامك أو حصصهم أو طابورهم.

## 7. استخدام Postman

استورد [مجموعة Postman](OPENWA_NUMBER_ONBOARDING_POSTMAN.json)، ثم اضبط:

| المتغير | القيمة |
|---|---|
| `base_url` | `https://notify.prideidea.com/api` |
| `session_id` | معرّف الجلسة التي أنشأتها من الداشبورد |
| `session_key` | مفتاح operator المقيد بالجلسة |
| `recipient_number` | رقم مستلم دولي مصرح بمراسلته، بالأرقام فقط |

لأن الجلسة موجودة ومرتبطة، ابدأ بطلب **Check status and actual phone**، ثم **Send text**. لا تنفذ طلب إنشاء جلسة أو بدء جلسة جديدة أو طلبات الإيقاف والإلغاء لمجرد الاختبار. استخدم مخزن الأسرار في Postman للمفاتيح ولا تشارك تصدير بيئة يحتويها.

## 8. الأخطاء وحدود هذا المسار

| الحالة | التصرف |
|---|---|
| `401` أو `403` | تحقق من المفتاح ودوره وصلاحيته وقيد الجلسة |
| `404` | تحقق من Session ID والعنوان |
| الجلسة ليست `ready` | راجع اتصال الرقم في الداشبورد؛ قد يلزم ربط جديد |
| `429` | خفف الطلبات؛ لا تنشئ حلقات إرسال متوازية |
| مهلة أو انقطاع أثناء POST | قد تكون الرسالة خرجت؛ لا تكررها تلقائياً |
| `5xx` أو رد غير واضح بعد POST | راجع النتيجة قبل إرسال نسخة أخرى |

هذا هو **الإرسال المباشر عبر OpenWA**. لا يوفر عقد الطابور الدائم ومنع التكرار الخاص بخدمة `/v1/notifications`. إذا احتجت إعادة محاولات آمنة، صمم في نظامك طابوراً وسجل محاولات ونتائج غير محسومة، أو استخدم خدمة الإشعارات وفق حدودها الحالية.

خدمة `/v1/notifications` الحالية تستخدم جلسة واحدة مضبوطة في خادمها؛ إنشاء جلسة جديدة في الداشبورد لا يغير مرسلها تلقائياً، ولا تدعم حالياً تمرير `session_id` أو اختيار مرسل لكل طلب.

## 9. التسليم وإلغاء المفتاح

لتأكيد التسليم والقراءة سجل Webhook موقّعاً للجلسة بأحداث `message.ack`، وتحقق من التوقيع على جسم الطلب الأصلي. الخطوات والأمثلة في [الدليل الكامل، قسم التسليم والقراءة](WHATSAPP_NUMBER_ONBOARDING_API_AR.md#6-التسليم-والقراءة-عبر-webhook).

لإيقاف صلاحية نظام معين، ألغ مفتاحه من **API Keys** أو من خادم الإدارة عبر `POST /api/auth/api-keys/{key_id}/revoke`. إلغاء مفتاح النظام لا يتطلب حذف الجلسة أو فصل الرقم عن التطبيقات الأخرى.

**خلاصة بيانات الربط التي تسلمها للنظام الثاني:** عنوان API، وSession ID، ومفتاح operator الخاص بالجلسة. لا يحتاج النظام الثاني إلى مفتاح إدارة الداشبورد.
