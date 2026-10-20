import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { useAuthStore } from "@features/auth/store/authStore";
import { getApiErrorMessage } from "@services/http/client";
import { messageAPI, type MessageConfig } from "./api";

export function MessageImage({
  eventId,
  imageId,
}: {
  eventId: string;
  imageId: string | null;
}) {
  const tenantId = useAuthStore((s) => s.currentTenantId);
  const [url, setUrl] = useState("");
  const query = useQuery({
    queryKey: ["whatsapp-message-image", tenantId, eventId, imageId],
    queryFn: ({ signal }) => messageAPI.image(eventId, imageId!, signal),
    enabled: !!imageId,
    retry: false,
    gcTime: 0,
  });
  useEffect(() => {
    setUrl("");
    if (!query.data) return;
    const objectUrl = URL.createObjectURL(query.data);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [query.data, imageId]);
  if (!imageId) return null;
  if (query.isError)
    return (
      <p role="alert">تعذر عرض الصورة. أعد فتح المعاينة للمحاولة مجدداً.</p>
    );
  return url ? (
    <img className="wa-message-image" src={url} alt="صورة رسالة الدعوة" />
  ) : (
    <Loader2 className="spin" aria-label="جارٍ تحميل الصورة" />
  );
}
const variables = [
  ["guest_name", "اسم الضيف"],
  ["event_name", "اسم الحدث"],
  ["event_date", "موعد الحدث"],
  ["event_location", "الموقع"],
];
export function WhatsAppMessageEditor({
  eventId,
  onClose,
  onBusy,
}: {
  eventId: string;
  onClose: () => void;
  onBusy: (busy: boolean) => void;
}) {
  const tenantId = useAuthStore((s) => s.currentTenantId),
    qc = useQueryClient();
  const query = useQuery({
    queryKey: ["whatsapp-message-config", tenantId, eventId],
    queryFn: ({ signal }) => messageAPI.get(eventId, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<MessageConfig | null>(null),
    [tab, setTab] = useState<"rsvp_text" | "ticket_text">("rsvp_text"),
    [error, setError] = useState("");
  const text = useRef<HTMLTextAreaElement>(null),
    fileInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (query.data) setDraft(query.data);
  }, [query.data]);
  const upload = useMutation({
    mutationFn: (file: File) => messageAPI.upload(eventId, file),
    onSuccess: (data) =>
      setDraft((d) => (d ? { ...d, image_id: data.image_id } : d)),
    onError: (e) => setError(getApiErrorMessage(e)),
  });
  const save = useMutation({
    mutationFn: () => messageAPI.save(eventId, draft!),
    onSuccess: async () => {
      await qc.invalidateQueries({
        queryKey: ["whatsapp-message-config", tenantId, eventId],
      });
      await qc.invalidateQueries({
        queryKey: ["whatsapp-message-preview", tenantId, eventId],
      });
      onClose();
    },
    onError: (e) => setError(getApiErrorMessage(e)),
  });
  const busy = upload.isPending || save.isPending;
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  const insert = (variable: string) => {
    if (!draft) return;
    const start = text.current?.selectionStart ?? draft[tab].length,
      end = text.current?.selectionEnd ?? start;
    const next =
      draft[tab].slice(0, start) + `{${variable}}` + draft[tab].slice(end);
    if (next.length > 700) return;
    setDraft({ ...draft, [tab]: next });
    requestAnimationFrame(() => {
      text.current?.focus();
      text.current?.setSelectionRange(
        start + variable.length + 2,
        start + variable.length + 2,
      );
    });
  };
  const message = draft
    ? draft[tab].replace(
        /\{(guest_name|event_name|event_date|event_location)\}/g,
        (_, key) => draft.sample_values[key] || "",
      ) +
      "\n\n" +
      draft.sample_link
    : "";
  return (
    <>
      <div className="wa-modal__body wa-editor-body">
        {query.isLoading ? (
          <Loader2 className="spin" />
        ) : query.isError ? (
          <p role="alert">
            {getApiErrorMessage(query.error)}{" "}
            <button onClick={() => query.refetch()}>إعادة المحاولة</button>
          </p>
        ) : (
          draft && (
            <>
              <p className="wa-muted">
                تُحفظ الرسالة لهذا الحدث. يُضاف اسم كل ضيف ورابط دعوته تلقائياً؛
                التعديل يطبق على الإرسال الجديد.
              </p>
              <div className="wa-editor-layout">
                <div className="wa-editor-fields">
                  <div
                    className="wa-message-tabs"
                    role="tablist"
                    aria-label="نوع رسالة WhatsApp"
                  >
                    <button
                      role="tab"
                      aria-selected={tab === "rsvp_text"}
                      disabled={busy}
                      onClick={() => setTab("rsvp_text")}
                    >
                      طلب تأكيد الحضور
                    </button>
                    <button
                      role="tab"
                      aria-selected={tab === "ticket_text"}
                      disabled={busy}
                      onClick={() => setTab("ticket_text")}
                    >
                      الدعوة النهائية
                    </button>
                  </div>
                  <label className="wa-editor-label" htmlFor="wa-message-body">
                    نص الرسالة
                  </label>
                  <textarea
                    id="wa-message-body"
                    ref={text}
                    value={draft[tab]}
                    disabled={busy}
                    maxLength={700}
                    rows={9}
                    onChange={(e) => {
                      setError("");
                      setDraft({ ...draft, [tab]: e.target.value });
                    }}
                  />
                  <div className="wa-editor-text-tools">
                    <small>{draft[tab].length} من 700 حرف</small>
                    <button
                      className="btn btn-ghost"
                      disabled={busy}
                      onClick={() =>
                        setDraft({ ...draft, [tab]: draft.defaults[tab] })
                      }
                    >
                      <RotateCcw size={14} />
                      استعادة النص المقترح
                    </button>
                  </div>
                  <div className="wa-template-variables">
                    {variables.map(([key, label]) => (
                      <button
                        className="btn btn-secondary"
                        key={key}
                        disabled={busy}
                        onClick={() => insert(key)}
                      >
                        + {label}
                      </button>
                    ))}
                  </div>
                  <small className="wa-muted">
                    اضغط المتغير لإدراجه عند المؤشر. رابط الضيف يُضاف أسفل النص
                    ولا يحتاج إلى كتابته.
                  </small>
                  <div className="wa-editor-image-tools">
                    <input
                      ref={fileInput}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      aria-label="رفع صورة الرسالة"
                      hidden
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = "";
                        if (!file) return;
                        setError("");
                        if (file.size > 5 * 1024 * 1024) {
                          setError("حجم الصورة يجب ألا يتجاوز 5MB.");
                          return;
                        }
                        upload.mutate(file);
                      }}
                    />
                    <button
                      className="btn btn-secondary"
                      disabled={busy}
                      onClick={() => fileInput.current?.click()}
                    >
                      {upload.isPending ? (
                        <Loader2 className="spin" size={16} />
                      ) : (
                        <ImagePlus size={16} />
                      )}{" "}
                      {draft.image_id ? "تغيير الصورة" : "إضافة صورة"}
                    </button>
                    {draft.image_id && (
                      <button
                        className="btn btn-ghost"
                        disabled={busy}
                        onClick={() => setDraft({ ...draft, image_id: null })}
                      >
                        <Trash2 size={14} />
                        إزالة الصورة
                      </button>
                    )}
                    <small>صورة واحدة للرسالتين • PNG، JPG، WEBP حتى 5MB</small>
                  </div>
                </div>
                <aside
                  className="wa-editor-preview"
                  aria-label="معاينة رسالة WhatsApp"
                >
                  <strong>كما ستصل للضيف</strong>
                  <div className="wa-chat-bubble">
                    <MessageImage eventId={eventId} imageId={draft.image_id} />
                    <p dir="auto">{message}</p>
                    <small>معاينة باسم افتراضي</small>
                  </div>
                  <small
                    className={
                      draft.image_id && message.length > 1024
                        ? "wa-error"
                        : "wa-muted"
                    }
                  >
                    {draft.image_id
                      ? `${message.length} / 1024 حرف مع الصورة`
                      : "ستُرسل رسالة نصية مع الرابط الفردي."}
                  </small>
                </aside>
              </div>
            </>
          )
        )}
        {error && (
          <p className="wa-error" role="alert">
            {error}{" "}
            <button
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => {
                setError("");
                void query.refetch();
              }}
            >
              إعادة تحميل الرسالة
            </button>
          </p>
        )}
      </div>
      <footer className="wa-modal__footer">
        <button className="btn btn-secondary" disabled={busy} onClick={onClose}>
          إلغاء
        </button>
        <button
          className="btn btn-primary"
          disabled={
            busy ||
            !draft ||
            !draft.rsvp_text.trim() ||
            !draft.ticket_text.trim() ||
            !!(draft.image_id && message.length > 1024)
          }
          onClick={() => {
            setError("");
            save.mutate();
          }}
        >
          {save.isPending && <Loader2 className="spin" size={16} />}حفظ الرسالة
        </button>
      </footer>
    </>
  );
}
