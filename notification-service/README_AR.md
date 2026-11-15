# خدمة الإشعارات المستقلة

العنوان المخصص: **https://notify.prideidea.com**. خدمة مستقلة عن أحداث ودعوات المنصة، بقاعدة بيانات SQLite/WAL داخل volume دائم، ومفتاح لكل نظام، وعامل إرسال واحد. القناة المنفذة في هذا الإصدار: رسائل WhatsApp النصية. لا يحتاج النظام المتصل حساب مستخدم في منصة الدعوات.

## النشر الحالي ومتطلبات النطاق

نُشرت الخدمة على الخادم في حاوية `notification-gateway-notification-api-1`، بلا منفذ عام مباشر، وخلف Caddy. شهادة Origin الموجودة تغطي `*.prideidea.com` وتتطلب الوصول عبر Cloudflare مع وضع SSL/TLS Full (strict). لا تستخدم DNS-only بهذه الشهادة لأنها ليست شهادة عامة موثوقة لدى المتصفحات.

أضيف سجل A للنطاق مع تفعيل Cloudflare Proxy، وتحقق الوصول العام عبر HTTPS بنتيجة 200. الإعداد الفعلي:

| النوع | الاسم | الهدف | Proxy |
|---|---|---|---|
| A | notify | 217.216.79.195 | مفعّل |

الـWebhook بين OpenWA والخدمة يمر عبر الشبكة الخاصة، فلا ينتظر DNS العام. لم يُغيّر Webhook الخاص بمنصة الدعوات؛ أُضيف اشتراك مستقل. تستخدم الخدمة حالياً جلسة WhatsApp القائمة بمفتاح operator مستقل مقيد بتلك الجلسة. قواعد البيانات والمفاتيح والطابور مستقلة؛ رقم WhatsApp ومزوّد OpenWA مشتركان مع المنصة، وأي فصل للجلسة يؤثر فيهما معاً. للاستقلال الكامل للمرسل خصص جلسة ورقماً آخرين وحدث إعداد الخدمة وأعد تسجيل Webhook.

## بدء ربط نظام جديد

ينشئ مسؤول الخادم مفتاحاً خاصاً بكل نظام:

```bash
python3 notification-service/manage.py create-client orders \
  --daily-limit 1000 --per-minute 30 \
  --output "$HOME/.qentry/orders-notifications.json"
```

الملف الناتج بصلاحية `600` يحتوي `id` و`api_key` و`base_url` وحدود الاستخدام. المفتاح يظهر عند الإنشاء فقط، وتخزن الخدمة SHA-256 له. سلم المفتاح لمسؤول النظام عبر قناة أسرار آمنة، واحفظه في بيئة خادم النظام؛ لا تضعه في JavaScript المتصفح أو Git. المفتاح الإداري منفصل، ولا يسلم للأنظمة المتصلة.

```dotenv
NOTIFY_BASE_URL=https://notify.prideidea.com
NOTIFY_API_KEY=<مفتاح النظام>
```

## إرسال إشعار

```bash
curl --fail-with-body "$NOTIFY_BASE_URL/v1/notifications" \
  -H "Authorization: Bearer $NOTIFY_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-123-confirmation-v1' \
  --data '{"channel":"whatsapp","to":"967775451608","text":"تم تأكيد طلبك رقم 123."}'
```

لا تنفذ المثال برقم حقيقي إلا إذا كنت تقصد إرسال الرسالة إليه. يتطلب كل طلب `Idempotency-Key` بطول 1–128، وحروف لاتينية وأرقام أو `_.:-`. أنشئ المفتاح واحفظه في النظام المصدر قبل الطلب، واستعمله نفسه عند انقطاع الشبكة. يعاد نفس الإشعار دون إرسال جديد إذا تطابق المحتوى؛ تغيير المحتوى بالمفتاح نفسه يعيد `409`. يعاد وضع الإشعار الحالي في الاستجابة المكررة، وقد يكون تجاوز `queued`.

تقبل الأرقام الدولية مع رمز البلد، مع أو دون `+`؛ لا تستنتج الخدمة بلد الرقم المحلي. النص بين 1 و4096 حرفاً، ولا يقبل نصاً فارغاً. لا يدعم هذا الإصدار صوراً أو ملفات أو مجموعات أو بريدًا أو SMS. الحقول الإضافية ترفض. حد جسم الطلب 64 KiB.

استجابة `202 Accepted`:

```json
{"id":"UUID","state":"queued","error_code":null,"created_at":1792480000.0,"updated_at":1792480000.0}
```

التوقيت Unix بالثواني UTC. `202` يعني حفظ الطلب في الطابور. احتفظ بـ`id` في سجل العملية التجارية.

## متابعة وإلغاء الرسالة

```bash
curl --fail-with-body "$NOTIFY_BASE_URL/v1/notifications/UUID" \
  -H "Authorization: Bearer $NOTIFY_API_KEY"

curl --fail-with-body "$NOTIFY_BASE_URL/v1/notifications?limit=50&offset=0" \
  -H "Authorization: Bearer $NOTIFY_API_KEY"

curl --fail-with-body -X POST "$NOTIFY_BASE_URL/v1/notifications/UUID/cancel" \
  -H "Authorization: Bearer $NOTIFY_API_KEY"
```

كل نظام يرى رسائله فقط؛ قراءة رسالة نظام آخر تعيد `404`. القوائم مرتبة من الأحدث، والحد الأقصى 100 في الصفحة. الإلغاء متاح قبل بدء الإرسال فقط؛ ما بدأ يعيد `409`.

| الحالة | معناها والتعامل معها |
|---|---|
| queued | محفوظ وينتظر العامل |
| waiting_connection | جلسة WhatsApp غير جاهزة؛ فحص جديد بعد 30 ثانية |
| sending | بدأت المحاولة الخارجية؛ يمنع إلغاؤها |
| sent | أعاد المزود معرف رسالة؛ لا يثبت وصولها |
| delivered | وصل إيصال تسليم موقع من المزود |
| read | وصل إيصال قراءة؛ قد لا يتاح بحسب إعدادات واتساب |
| failed | رفض مؤكد، أو مراجعة يدوية، أو إيصال رفض من واتساب |
| unknown | قد تكون أُرسلت؛ تحقق من هاتف المرسل قبل أي إرسال جديد |
| cancelled | ألغيت قبل بدء المحاولة |

تتم متابعة الأنظمة عن طريق GET دوري، مثلاً كل 10 ثوانٍ مع إبطاء تدريجي. **لا توجد في الإصدار الحالي Webhooks صادرة إلى الأنظمة العميلة**. الـWebhook المنفذ وارد من OpenWA إلى الخدمة لإثبات التسليم والقراءة، بتوقيع HMAC-SHA256؛ يحتفظ بالإيصالات المبكرة قبل عودة معرف الرسالة، ويمنع تكرارها أو تخفيض حالة القراءة إلى التسليم.

## مثال Python

```python
import os
import httpx

base = os.environ['NOTIFY_BASE_URL'].rstrip('/')
headers = {
    'Authorization': 'Bearer ' + os.environ['NOTIFY_API_KEY'],
    'Idempotency-Key': 'order-123-confirmation-v1',  # محفوظ مع العملية التجارية
}
with httpx.Client(timeout=30) as client:
    response = client.post(base + '/v1/notifications', headers=headers,
        json={'channel': 'whatsapp', 'to': '967775451608',
              'text': 'تم تأكيد طلبك رقم 123.'})
    response.raise_for_status()
    notification_id = response.json()['id']
    status = client.get(base + '/v1/notifications/' + notification_id,
        headers={'Authorization': headers['Authorization']})
    status.raise_for_status()
    print(status.json()['state'])
```

عند timeout أعد POST بالمفتاح والمحتوى نفسيهما. لا تنشئ مفتاحاً جديداً لمجرد ضياع الرد.

## مثال Node.js

```javascript
const base = process.env.NOTIFY_BASE_URL;
const headers = {
  Authorization: `Bearer ${process.env.NOTIFY_API_KEY}`,
  'Content-Type': 'application/json',
  'Idempotency-Key': 'order-123-confirmation-v1',
};
const response = await fetch(`${base}/v1/notifications`, {
  method: 'POST', headers,
  body: JSON.stringify({ channel: 'whatsapp', to: '967775451608',
    text: 'تم تأكيد طلبك رقم 123.' }),
  signal: AbortSignal.timeout(30000),
});
if (!response.ok) throw new Error(`Notification API: ${response.status}`);
const notification = await response.json();
// احفظ notification.id وتابع GET حتى تتضح النتيجة.
```

## حدود الاستخدام والأخطاء

الحد اليومي لكل نظام يحسب الطلبات المقبولة منذ منتصف الليل UTC، بما فيها الفاشلة والملغاة، ولا يحسب تكرار المفتاح نفسه. حد الدقيقة نافذة 60 ثانية للطلبات الجديدة المقبولة. كلاهما حدود قبول، ولا يضمنان سرعة التسليم. العامل يرسل محاولة واحدة كل خمس ثوانٍ على الأقل للخدمة كلها. الطلبات تبقى في الطابور عند انقطاع الجلسة. لا يوجد انتهاء تلقائي للرسائل أو حذف تلقائي للبيانات في هذا الإصدار؛ راقب نمو التخزين والطابور، ولا تعتمد عليه لتنبيهات لها مهلة قصيرة دون إضافة صلاحية زمنية.

| HTTP | المعنى |
|---|---|
| 401 | مفتاح مفقود أو غير صحيح أو ملغى |
| 404 | رسالة غير موجودة أو تخص نظاماً آخر |
| 409 | تعارض مفتاح تكرار أو عملية لا تسمح بها الحالة |
| 413 | جسم طلب كبير |
| 422 | حقول أو رقم أو مفتاح تكرار غير صالح |
| 429 | حد قبول يومي أو في الدقيقة؛ Retry-After=60 وإعادة المحاولة بالمفتاح نفسه؛ الحد اليومي ينتظر يوم UTC التالي |
| 503 | مزود غير متاح في مسار الإدارة أو عامل غير سليم في فحص الجاهزية |

## واجهات الإدارة

تستخدم `Authorization: Bearer <NOTIFY_ADMIN_KEY>`، وهي مفتاح مستقل لا يعمل كمفتاح إرسال عميل.

| الطريقة | المسار | الوظيفة |
|---|---|---|
| POST | /v1/admin/clients | إنشاء نظام: name وdaily_limit وper_minute |
| GET | /v1/admin/clients | قائمة الأنظمة وحدودها وحالة تفعيلها |
| POST | /v1/admin/clients/{id}/rotate | تدوير المفتاح فوراً؛ الجديد يظهر مرة واحدة |
| DELETE | /v1/admin/clients/{id} | إلغاء المفتاح وإلغاء الرسائل التي لم تبدأ |
| GET | /v1/admin/connection | حالة الجلسة الحية ورقم المرسل |
| GET | /v1/admin/notifications | متابعة جميع الأنظمة؛ limit وoffset وstate اختيارية |
| POST | /v1/admin/notifications/{id}/review | حسم unknown فقط مع دليل |
| GET | /v1/admin/audit | سجل إنشاء المفاتيح وتدويرها وإلغائها والمراجعات |

إنشاء نظام: `{"name":"orders","daily_limit":1000,"per_minute":30}`.
مراجعة نتيجة غير محسومة: `{"outcome":"sent","evidence":"تم التحقق من وجود الرسالة على هاتف المرسل في الوقت المحدد"}`؛ أو `outcome=not_sent`. الدليل من 20 إلى 500 حرف. المراجعة لا تعيد إرسال شيء، ولا تعيد حصة القبول. إذا ثبت عدم الإرسال واحتجت رسالة جديدة، أنشئ طلباً جديداً بمفتاح مختلف مقصود.

تدوير المفتاح يبطل القديم فوراً ويبقي طلبات النظام؛ الإلغاء يمنع الطلبات الجديدة ويلغي الانتظار. محاولة بدأت قبل الإلغاء قد تكتمل. لا يوجد endpoint لإعادة تفعيل عميل ملغى؛ أنشئ عميلاً جديداً عند الحاجة.

التوثيق التفاعلي: `/docs`، وOpenAPI: `/openapi.json`، وReDoc: `/redoc`. الواجهات موثقة للعامة، والمفاتيح مطلوبة لتنفيذ العمليات المحمية.

## التشغيل والنسخ والاستعادة

الأسرار في `/home/alrazi/.qentry/notifications.env` بصلاحية `600`، خارج Git. يحتوي مفتاح الإدارة ومفتاح المزود المقيد ومعرف الجلسة وسر Webhook. يمكن تغيير مسار الملف عبر `NOTIFY_ENV_FILE`.

```bash
# إعداد أولي فقط؛ يرفض استبدال ملف أسرار موجود
python3 notification-service/provision.py SESSION_UUID
# بناء وتشغيل أو تحديث
 docker compose -f notification-service/compose.yml up -d --build
# تسجيل Webhook مستقل؛ آمن للتكرار لنفس عنوان callback
python3 notification-service/register_webhook.py
# فحص اتصال المرسل
python3 notification-service/manage.py connection
# الحاوية وحالة العامل
 docker compose -f notification-service/compose.yml ps
# اختبارات معزولة؛ لا إرسال واتساب فعلي
.venv/bin/python -m unittest discover -s notification-service/tests -v
```

`/health/live` يفحص التطبيق، و`/health/ready` يفحص نبض العامل والقدرة على قراءة قاعدة البيانات. الجاهزية لا تعني اتصال واتساب؛ افحص `/v1/admin/connection` لذلك. عند إيقاف العامل بعد بدء إرسال لا تعاد المحاولة؛ بعد 120 ثانية تتحول `sending` العالقة إلى `unknown`. لا تعد ارسالاً ناجحاً إذا ضاع رد المزود.

يجب تشغيل نسخة واحدة وعامل Uvicorn واحد بهذه البنية. SQLite مناسب لهذه العقدة الواحدة؛ للتوسع إلى عدة خوادم يلزم نقل الطابور إلى PostgreSQL مع claim/lease وقفل مشترك. لا تشغل نسخاً مستقلة ببيانات متفرقة خلف موازن واحد.

البيانات في Docker volume `notification-gateway_notifications`. النسخ عبر SQLite backup API، دون نسخ ملف حي وحده وإهمال WAL:

```bash
BACKUP_GPG_RECIPIENT=<معرف-مفتاح-GPG> notification-service/backup.sh
```

احفظ ملف الأسرار ونسخ OpenWA وجلساته أيضاً بنسخ احتياطية مشفرة منفصلة. سكربت النسخ لا يحذف نسخاً قديمة أو ينقلها خارج الخادم؛ اضبط ذلك حسب سياسة التشغيل. للاستعادة: أوقف الحاوية، فك تشفير النسخة إلى مسار محمي، تحقق من `PRAGMA integrity_check`، استبدل قاعدة البيانات داخل volume مع حذف ملفات WAL/SHM القديمة فقط أثناء التوقف واضبط ملكيتها UID 10001، استعد ملف الأسرار، ثم شغل الخدمة وافحصها. لا ترسل من قاعدة مستعادة قديمة قبل مراجعة الرسائل التي يحتمل أنها خرجت بعد نقطة النسخ؛ snapshot قديمة قد تحتوي queued أُرسلت لاحقاً. عالجها كمحاولات غير محسومة قبل استئناف العامل.

لتغيير الأسرار أو إعدادات المرسل: حدث ملف البيئة ثم `docker compose ... up -d --force-recreate`. تغيير سر Webhook أو الجلسة يحتاج إعادة تشغيل وتسجيل Webhook أيضاً. لا تغير قاعدة بيانات الخدمة أو سياق RLS في المنصة لعلاج مشكلة فحص.


## نتائج التحقق المنشور

- فحص HTTPS العام و`/health/ready` و`/docs` و`/openapi.json`: HTTP 200.
- محاولة قائمة الأنظمة دون مفتاح: HTTP 401.
- جلسة المرسل: `ready`، والحاوية `healthy`.
- اختبارات معزولة ناجحة لمنع التكرار وتعارض المحتوى وعزل الأنظمة والحدود وإلغاء المفاتيح، وانقطاع النقل واستعادة sending، والإيصالات المبكرة والتوقيع وترتيب حالات القراءة.
- أرسلت رسالة اختبار واحدة عبر النطاق العام إلى الرقم الذي سبق التصريح باختباره. أعاد طلب الإرسال 202، وأعادت نسخته المكررة معرف الإشعار نفسه، ثم أصبحت الحالة `sent`. لم يثبت إيصال تسليم أو قراءة لهذه الرسالة وقت الفحص.
- تم توليد مفتاح أول نظام في `/home/alrazi/.qentry/notification-first-system.json` بصلاحية 600. لا يتضمن هذا المستند المفتاح نفسه.

يمكن استيراد `openapi.json` في Postman أو استخدام `postman_collection.json` مع متغيري `base_url` و`api_key`. تظل الأسرار خارج ملفات التوثيق.

نجح أيضاً اختبار Webhook تجريبي موقع من OpenWA إلى الخدمة بنتيجة HTTP 200، والتحقق من بقاء الإشعار نفسه بحالة `sent` بعد إعادة تشغيل الحاوية. عدد إشعارات الاختبار المحفوظة واحد؛ أُلغي مفتاح نظام الاختبار بعد الفحص. الأدلة المختصرة في `DEPLOYMENT.json`، ولا تحتوي مفاتيح أو أسراراً.

## لوحة إدارة أرقام WhatsApp

نُشرت لوحة OpenWA الأصلية على **https://notify.prideidea.com/dashboard**. تفاصيل الدخول وإضافة جلسة ورقم جديد في [دليل اللوحة](../docs/OPENWA_DASHBOARD_AR.md). مفتاح اللوحة منفصل عن مفاتيح خدمة الإشعارات. إضافة جلسة لا تغير مرسل خدمة الإشعارات تلقائياً؛ الخدمة الحالية تستخدم جلسة واحدة محددة في إعداداتها.

دليل الربط التفصيلي للمسارين، من الواجهة أو API، وإصدار مفتاح جلسة والإرسال وإيصالات التسليم: [ربط الأرقام والإرسال عبر API](../docs/WHATSAPP_NUMBER_ONBOARDING_API_AR.md).
