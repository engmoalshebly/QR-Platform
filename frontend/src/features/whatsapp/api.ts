import http from "@services/http/client";
export interface Connection {
  configured: boolean;
  feature_enabled: boolean;
  linked: boolean;
  enabled: boolean;
  status: string;
  phone: string | null;
  last_checked_at: string | null;
}
export interface Delivery {
  id: string;
  invitation_id: string;
  guest_name: string;
  recipient: string;
  purpose: string;
  state: string;
  error_code: string | null;
  created_at: string;
}
export interface DeliverySummary extends Omit<Delivery, "guest_name"> {
  updated_at: string;
  attempt_count: number;
}
export interface DeliveryPage {
  items: Delivery[];
  total: number;
  limit: number;
  offset: number;
  as_of: string;
}
export const whatsappAPI = {
  connection: () =>
    http.get<Connection>("/whatsapp/connection").then((r) => r.data),
  link: () => http.post("/whatsapp/connection/link").then((r) => r.data),
  refresh: () =>
    http
      .post<{
        status: string;
        phone: string | null;
      }>("/whatsapp/connection/refresh")
      .then((r) => r.data),
  qr: () =>
    http.get<{ qrCode: string }>("/whatsapp/connection/qr").then((r) => r.data),
  enable: (enabled: boolean) =>
    http.put("/whatsapp/connection", { enabled }).then((r) => r.data),
  send: (
    invitation_ids: string[],
    client_request_id: string,
    allow_resend: boolean,
    message_versions?: Record<string, number>,
  ) =>
    http
      .post<{
        queued: number;
        skipped: number;
        items: { invitation_id: string; reason?: string }[];
      }>("/whatsapp/deliveries", { invitation_ids, client_request_id, allow_resend, message_versions })
      .then((r) => r.data),
  history: (event_id: string, offset = 0, invitation_id?: string) =>
    http
      .get<
        Delivery[]
      >("/whatsapp/deliveries", { params: { event_id, offset, limit: 50, invitation_id } })
      .then((r) => r.data),
  historyPage: (
    params: {
      event_id: string;
      invitation_id?: string;
      search: string;
      state: string;
      purpose: string;
      limit: number;
      offset: number;
      as_of?: string;
    },
    signal?: AbortSignal,
  ) =>
    http
      .get<DeliveryPage>("/whatsapp/deliveries/page", { params, signal })
      .then((r) => r.data),
  summary: async (event_id: string, ids: string[]) => {
    const chunks: string[][] = [];
    for (let i = 0; i < ids.length; i += 100)
      chunks.push(ids.slice(i, i + 100));
    const results = await Promise.all(
      chunks.map((chunk) =>
        http
          .get<DeliverySummary[]>("/whatsapp/deliveries/summary", {
            params: { event_id, invitation_ids: chunk.join(",") },
          })
          .then((r) => r.data),
      ),
    );
    return results.flat();
  },
  review: (id: string, outcome: string, note: string) =>
    http
      .post(`/whatsapp/deliveries/${id}/review`, { outcome, note })
      .then((r) => r.data),
  cancel: (id: string) =>
    http.post(`/whatsapp/deliveries/${id}/cancel`).then((r) => r.data),
};
export const stateLabel: Record<string, string> = {
  not_connected: "لم يُربط رقم WhatsApp",
  created: "بانتظار بدء الربط",
  initializing: "جارٍ تجهيز الاتصال",
  qr_ready: "امسح رمز الربط",
  authenticating: "جارٍ التحقق",
  ready: "متصل",
  disconnected: "منقطع",
  unavailable: "تعذر الوصول",
  queued: "بانتظار التنفيذ",
  waiting_connection: "بانتظار الاتصال",
  sending: "جارٍ الإرسال",
  sent: "تم الإرسال",
  delivered: "تم التسليم",
  read: "تمت القراءة",
  failed: "فشلت",
  unknown: "نتيجة الإرسال غير مؤكدة",
  cancelled: "ملغاة",
};
export const reasonLabel: Record<string, string> = {
  whatsapp_rejected: "أبلغ WhatsApp بتعذر إرسال الرسالة",
  message_too_long: "النص يتجاوز حد الرسالة بعد تخصيصه للضيف",
  message_image_unavailable: "صورة الرسالة غير متاحة",
  manually_reviewed: "حُسمت النتيجة بمراجعة المسؤول",
  subscription_expired: "انتهى الاشتراك",
  invalid_phone: "رقم دولي غير صالح",
  already_pending: "يوجد إرسال جارٍ",
  already_sent: "سبق الإرسال",
  requires_review: "نتيجة إرسال سابقة غير مؤكدة",
  not_found: "الدعوة غير متاحة",
  event_unavailable: "المناسبة غير متاحة",
  invitation_unavailable: "الدعوة ملغاة أو اعتذر الضيف",
  invitation_expired: "انتهت الدعوة",
  registration_only: "طلب تسجيل وليس تذكرة",
  authorization_lost: "تغيرت الصلاحية أو تفعيل الخدمة",
  connection_unavailable: "الرقم غير متصل",
  invitation_changed: "تغيرت الدعوة أو بيانات الاتصال",
  entitlement_or_quota: "الميزة أو رصيد الرسائل غير متاح",
  provider_rejected: "رفضت خدمة الإرسال الطلب",
  send_result_unknown: "نتيجة الإرسال غير مؤكدة",
  worker_interrupted: "توقف العامل أثناء المحاولة",
  connection_disabled: "عُطل اتصال المؤسسة",
  cancelled_by_user: "ألغاها المستخدم",
};

export interface MessageConfig {
  rsvp_text: string;
  ticket_text: string;
  image_id: string | null;
  version: number;
  defaults: { rsvp_text: string; ticket_text: string };
  sample_values: Record<string, string>;
  sample_link: string;
}
export interface MessagePreview {
  version: number;
  image_id: string | null;
  too_long: number;
  samples: { purpose: string; text: string; guest_name: string }[];
}
export const messageAPI = {
  get: (eventId: string, signal?: AbortSignal) =>
    http
      .get<MessageConfig>(`/whatsapp/events/${eventId}/message`, { signal })
      .then((r) => r.data),
  save: (
    eventId: string,
    data: Pick<
      MessageConfig,
      "rsvp_text" | "ticket_text" | "image_id" | "version"
    >,
  ) =>
    http
      .put<MessageConfig>(`/whatsapp/events/${eventId}/message`, data)
      .then((r) => r.data),
  upload: (eventId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http
      .post<{
        image_id: string;
        size: number;
      }>(`/whatsapp/events/${eventId}/message/image`, form, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },
  image: (eventId: string, imageId: string, signal?: AbortSignal) =>
    http
      .get<Blob>(`/whatsapp/events/${eventId}/message/images/${imageId}`, {
        responseType: "blob",
        signal,
      })
      .then((r) => r.data),
  preview: (eventId: string, ids: string[], signal?: AbortSignal) =>
    http
      .post<MessagePreview>(
        `/whatsapp/events/${eventId}/message/preview`,
        { invitation_ids: ids },
        { signal },
      )
      .then((r) => r.data),
};
