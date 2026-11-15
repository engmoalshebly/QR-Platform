# إرسال صورة مع نص عبر WhatsApp API

## المتطلبات

- جلسة مرتبطة من الداشبورد وحالتها **Connected / ready**.
- **Session ID** من تفاصيل الجلسة.
- مفتاح **API Key كامل** بدور `operator` أو `admin`؛ يفضل مفتاح operator مقيداً بالجلسة.

أنشئ المفتاح من **الداشبورد ← API Keys ← Create API Key** وانسخه عند ظهوره، لا تستخدم `Key Prefix` المختصر. إصدار مفتاح مقيد بالجلسة موضح في [دليل الربط](OPENWA_SEND_AFTER_DASHBOARD_AR.md#2-جهز-مفتاحا-خاصا-بهذه-الجلسة).

## الطلب في Postman أو أي نظام

اختر **POST** واستخدم الرابط، مع استبدال `SESSION_ID` بمعرف جلستك:

```text
https://notify.prideidea.com/api/sessions/SESSION_ID/messages/send-image
```

**Headers:**

| الاسم | القيمة |
|---|---|
| X-API-Key | المفتاح الكامل |
| Content-Type | application/json |

**Body ← JSON:**

```json
{
  "chatId": "RECIPIENT_NUMBER@c.us",
  "url": "https://your-domain.com/images/invitation.jpg",
  "caption": "مرحباً، هذه دعوتك. يسعدنا حضورك."
}
```

استبدل `RECIPIENT_NUMBER` برقم المستلم الدولي بالأرقام فقط دون `+` أو مسافات. استبدل `url` برابط HTTPS مباشر لصورة يمكن لخادم OpenWA تحميلها دون تسجيل دخول؛ لا تستخدم رابط صفحة عرض أو مسار ملف محلي أو `blob:`.

| الحقل | الاستخدام |
|---|---|
| chatId | رقم المستلم متبوعاً بـ`@c.us` |
| url | رابط الصورة المباشر |
| caption | النص المرفق بالصورة، بحد أقصى 1024 حرفاً |

النص هنا في **`caption`** وليس `text`. تصل الصورة والنص كرسالة وسائط واحدة.

## مثال curl

حمّل `SESSION_ID` و`API_KEY` من إعدادات خادمك، ثم استبدل رقم المستلم ورابط الصورة في JSON. تنفيذ الطلب بقيم صحيحة يرسل رسالة فعلية.

```bash
curl --fail-with-body --request POST \
  "https://notify.prideidea.com/api/sessions/$SESSION_ID/messages/send-image" \
  --header "X-API-Key: $API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "chatId": "RECIPIENT_NUMBER@c.us",
    "url": "https://your-domain.com/images/invitation.jpg",
    "caption": "مرحباً، هذه دعوتك. يسعدنا حضورك."
  }'
```

## بديل الصورة المحلية: Base64

حوّل الصورة في خادم نظامك إلى Base64 وأرسلها **بدلاً من `url`**:

```json
{
  "chatId": "RECIPIENT_NUMBER@c.us",
  "base64": "BASE64_IMAGE_CONTENT",
  "mimetype": "image/jpeg",
  "filename": "invitation.jpg",
  "caption": "مرحباً، هذه دعوتك."
}
```

`base64` محتوى الترميز فقط دون بادئة `data:image/...;base64,`. استخدم `image/png` إذا كانت الصورة PNG. حد جسم الطلب المنشور **64 KiB**، لذا يناسب Base64 الصور الصغيرة فقط؛ حد الجسم يشمل الترميز والنص وبقية JSON. استخدم رابط الصورة للصور الأكبر.

## نتيجة الإرسال

```json
{
  "messageId": "provider-message-id",
  "timestamp": 1792470000
}
```

احفظ `messageId`. الاستجابة تؤكد نتيجة الإرسال لدى المزود، ولا تثبت الوصول أو القراءة. إذا انقطع الاتصال أثناء الإرسال فلا تكرر الطلب تلقائياً؛ قد تكون الرسالة أُرسلت بالفعل.

هذا المسار تابع لـ**OpenWA المباشر `/api`**؛ خدمة الإشعارات **`/v1/notifications`** تدعم النصوص فقط حالياً. احتفظ بالمفتاح على خادم نظامك، ولا تضعه في كود المتصفح.
