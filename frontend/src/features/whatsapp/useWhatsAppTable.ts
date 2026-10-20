import { useEffect, useMemo, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useAuthStore } from "@features/auth/store/authStore";
import { PERM, usePermission } from "@shared/permissions";
import type { Invitation } from "@features/invitations/types";
import type { InvitationTablePage } from "@features/invitations/types";
import { getApiErrorMessage } from "@services/http/client";
import {
  whatsappAPI,
  messageAPI,
  type DeliverySummary,
  type MessagePreview,
  reasonLabel,
} from "./api";

export const deliveryLabels: Record<string, string> = {
  not_sent: "لم تُرسل",
  queued: "في الطابور",
  waiting_connection: "بانتظار الاتصال",
  sending: "جارٍ الإرسال",
  sent: "تم الإرسال",
  delivered: "تم التسليم",
  read: "تمت القراءة",
  failed: "فشل الإرسال",
  unknown: "تحتاج مراجعة",
  cancelled: "أُلغي الإرسال",
  loading: "جارٍ التحقق",
  unavailable: "الحالة غير متاحة",
};
export function messagePurpose(inv: Invitation) {
  const required =
    String(inv.metadata?.require_rsvp).toLowerCase() === "true" ||
    (inv.metadata?.require_rsvp === undefined &&
      ["pending", "maybe"].includes(inv.rsvp_status || ""));
  return required && inv.rsvp_status !== "accepted" ? "rsvp" : "ticket";
}
export const purposeLabel = (purpose: string) =>
  purpose === "rsvp" ? "طلب تأكيد الحضور" : "رابط الدعوة";
function unavailableReason(inv: Invitation) {
  if (inv.is_registration) return "طلب تسجيل وليس تذكرة";
  if (
    ["revoked", "expired", "declined"].includes(inv.status) ||
    inv.rsvp_status === "declined"
  )
    return "الدعوة غير مؤهلة للإرسال";
  if (inv.expires_at && new Date(inv.expires_at).getTime() <= Date.now())
    return "انتهت صلاحية الدعوة";
  let phone = (inv.guest_whatsapp || inv.guest_phone || "")
    .trim()
    .replace(/[\s()-]/g, "");
  if (phone.startsWith("00")) phone = phone.slice(2);
  if (phone.startsWith("+")) phone = phone.slice(1);
  return /^[1-9][0-9]{7,14}$/.test(phone)
    ? ""
    : "أضف رقم WhatsApp دولياً صالحاً";
}

export function useWhatsAppTable(
  eventId: string,
  invitations: Invitation[],
  options?: {
    page: UseQueryResult<InvitationTablePage>;
    filter: string;
    setFilter: (value: string) => void;
    scope: string;
    searching: boolean;
  },
) {
  const tenantId = useAuthStore((s) => s.currentTenantId);
  const sendPermission = usePermission(PERM.WHATSAPP_SEND);
  const invitationSendPermission = usePermission(PERM.INV_SEND);
  const canSend = sendPermission && invitationSendPermission;
  const canView = usePermission(PERM.WHATSAPP_VIEW);
  const canManage = usePermission(PERM.WHATSAPP_MANAGE);
  const canEditMessage =
    usePermission(PERM.EVENT_TAB_SETTINGS) && sendPermission;
  const [editorOpen, setEditorOpen] = useState(false);
  const qc = useQueryClient();
  const [localFilter, setLocalFilter] = useState("all");
  const filter = options?.filter ?? localFilter;
  const setFilter = options?.setFilter ?? setLocalFilter;
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<Invitation[] | null>(null);
  const [resend, setResend] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [excluded, setExcluded] = useState<
    { invitation_id: string; reason?: string }[]
  >([]);
  const [historyScope, setHistoryScope] = useState<{
    invitationId?: string;
  } | null>(null);
  const [offset, setOffset] = useState(0);
  const [historySearch, setHistorySearch] = useState("");
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyState, setHistoryState] = useState("all");
  const [historyPurpose, setHistoryPurpose] = useState("all");
  const [historyLimit, setHistoryLimit] = useState(50);
  const [historyAnchor, setHistoryAnchor] = useState<string | undefined>();
  useEffect(() => {
    const timer = window.setTimeout(() => setHistoryQuery(historySearch), 300);
    return () => window.clearTimeout(timer);
  }, [historySearch]);
  useEffect(() => {
    setOffset(0);
    setHistoryAnchor(undefined);
  }, [historyQuery, historyState, historyPurpose, historyLimit]);
  const attempt = useRef<{
    signature: string;
    id: string;
    versions: Record<string, number>;
    preview: MessagePreview;
  } | null>(null);
  const conn = useQuery({
    queryKey: ["whatsapp-connection", tenantId],
    queryFn: whatsappAPI.connection,
    enabled: canSend || canView,
  });
  const visible = !!conn.data?.feature_enabled && (canSend || canView);
  const ids = useMemo(() => invitations.map((i) => i.id).sort(), [invitations]);
  const standaloneSummary = useQuery({
    queryKey: ["whatsapp-summary", tenantId, eventId, ids],
    queryFn: () => whatsappAPI.summary(eventId, ids),
    enabled: !options && visible && canView && ids.length > 0,
    retry: false,
    refetchInterval: (query) =>
      visible
        ? Math.min(
            (query.state.data?.some((row) =>
              ["queued", "waiting_connection", "sending"].includes(row.state),
            )
              ? 15000
              : 30000) *
              2 ** query.state.fetchFailureCount,
            120000,
          )
        : false,
  });
  const summary = options
    ? {
        data: options.page.data?.whatsapp ?? undefined,
        isError: options.page.isError,
        isFetching: options.page.isFetching,
        refetch: options.page.refetch,
      }
    : standaloneSummary;
  const deliveries = useMemo(
    () =>
      new Map(
        (summary.data || []).map((d) => [`${d.invitation_id}:${d.purpose}`, d]),
      ),
    [summary.data],
  );
  const currentDelivery = (inv: Invitation) =>
    deliveries.get(`${inv.id}:${messagePurpose(inv)}`);
  const statusFor = (inv: Invitation) =>
    currentDelivery(inv)?.state ||
    (summary.data ? "not_sent" : summary.isError ? "unavailable" : "loading");
  const reasonFor = (inv: Invitation) =>
    (options?.searching ? "انتظر اكتمال البحث" : "") ||
    unavailableReason(inv) ||
    ([...deliveries.values()].some(
      (d) =>
        d.invitation_id === inv.id &&
        ["queued", "waiting_connection", "sending", "unknown"].includes(
          d.state,
        ),
    )
      ? "توجد رسالة جارية أو نتيجة تحتاج مراجعة"
      : canView && !summary.data && ids.length
        ? "انتظر التحقق من حالة الإرسال"
        : "");
  const matchesFilter = (inv: Invitation) =>
    !visible ||
    !canView ||
    filter === "all" ||
    (filter === "sent"
      ? ["sent", "delivered", "read"].includes(statusFor(inv))
      : filter === "pending"
        ? ["queued", "waiting_connection", "sending"].includes(statusFor(inv))
        : statusFor(inv) === filter);
  const busy = !!confirm;
  const selectedInvitations = invitations.filter(
    (i) => selected.includes(i.id) && !reasonFor(i),
  );
  const invalidate = () =>
    Promise.all([
      qc.invalidateQueries({
        queryKey: ["whatsapp-summary", tenantId, eventId],
      }),
      qc.invalidateQueries({
        queryKey: ["whatsapp-history", tenantId, eventId],
      }),
      qc.invalidateQueries({ queryKey: ["invitations", tenantId, "table"] }),
    ]);
  const preview = useQuery({
    queryKey: [
      "whatsapp-message-preview",
      tenantId,
      eventId,
      confirm?.map((i) => i.id),
    ],
    queryFn: ({ signal }) =>
      messageAPI.preview(
        eventId,
        confirm!.map((i) => i.id),
        signal,
      ),
    enabled: !!confirm && canSend,
    retry: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
  });
  const send = useMutation({
    mutationFn: async () => {
      const sendIds = confirm!.map((i) => i.id);
      const signature = JSON.stringify({ ids: [...sendIds].sort(), resend });
      if (attempt.current?.signature !== signature)
        attempt.current = {
          signature,
          id: crypto.randomUUID(),
          versions: { [eventId]: preview.data!.version },
          preview: preview.data!,
        };
      return whatsappAPI.send(
        sendIds,
        attempt.current.id,
        resend,
        attempt.current.versions,
      );
    },
    onSuccess: (result) => {
      setFeedback(
        `أُضيفت ${result.queued} رسالة للطابور${result.skipped ? `؛ استُبعدت ${result.skipped}` : ""}.`,
      );
      setExcluded(result.items.filter((i) => i.reason));
      setSelected([]);
      setConfirm(null);
      setResend(false);
      attempt.current = null;
      void invalidate();
    },
    onError: (error) => {
      const code = (
        error as { response?: { data?: { detail?: { code?: string } } } }
      )?.response?.data?.detail?.code;
      if (code === "WHATSAPP_MESSAGE_CHANGED") {
        attempt.current = null;
        setConfirm(null);
      }
      setFeedback(getApiErrorMessage(error));
    },
  });
  const confirmationSignature = JSON.stringify({
    ids: confirm?.map((i) => i.id).sort(),
    resend,
  });
  const previewData =
    attempt.current?.signature === confirmationSignature
      ? attempt.current.preview
      : preview.data;
  const previewImage = useQuery({
    queryKey: [
      "whatsapp-message-image",
      tenantId,
      eventId,
      previewData?.image_id,
    ],
    queryFn: ({ signal }) =>
      messageAPI.image(eventId, previewData!.image_id!, signal),
    enabled: !!confirm && !!previewData?.image_id,
    retry: false,
    gcTime: 0,
  });
  const history = useQuery({
    queryKey: [
      "whatsapp-history",
      tenantId,
      eventId,
      historyScope?.invitationId,
      offset,
      historyLimit,
      historyQuery,
      historyState,
      historyPurpose,
      historyAnchor,
    ],
    queryFn: ({ signal }) =>
      whatsappAPI.historyPage(
        {
          event_id: eventId,
          offset,
          invitation_id: historyScope?.invitationId,
          search: historyQuery,
          state: historyState,
          purpose: historyPurpose,
          limit: historyLimit,
          as_of: historyAnchor,
        },
        signal,
      ),
    enabled: !!historyScope && canView,
    refetchInterval: historyScope ? 15000 : false,
    retry: false,
    gcTime: 60000,
  });
  const cancel = useMutation({
    mutationFn: whatsappAPI.cancel,
    onSuccess: () => {
      void invalidate();
    },
    onError: (error) => setFeedback(getApiErrorMessage(error)),
  });
  const review = useMutation({
    mutationFn: ({
      id,
      outcome,
      note,
    }: {
      id: string;
      outcome: string;
      note: string;
    }) => whatsappAPI.review(id, outcome, note),
    onSuccess: () => {
      void invalidate();
    },
    onError: (error) => setFeedback(getApiErrorMessage(error)),
  });
  useEffect(() => {
    setSelected([]);
    setConfirm(null);
    setEditorOpen(false);
    setResend(false);
    setFeedback("");
    setExcluded([]);
    setFilter("all");
    setHistoryScope(null);
    setOffset(0);
    attempt.current = null;
  }, [tenantId, eventId]);
  useEffect(() => {
    if (options?.scope) {
      setSelected([]);
      setConfirm(null);
      setFeedback("");
      setExcluded([]);
    }
  }, [options?.scope]);
  const openHistory = (invitationId?: string) => {
    setOffset(0);
    setHistorySearch("");
    setHistoryQuery("");
    setHistoryState("all");
    setHistoryPurpose("all");
    setHistoryAnchor(undefined);
    setHistoryScope({ invitationId });
  };
  const navigateHistory = (value: number) => {
    setHistoryAnchor(history.data?.as_of);
    setOffset(value);
  };
  const refreshHistory = () => {
    setOffset(0);
    setHistoryAnchor(undefined);
    void history.refetch();
  };
  const toggle = (id: string) =>
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((value) => value !== id)
        : previous.length < 100
          ? [...previous, id]
          : previous,
    );
  const selectRows = (rows: Invitation[]) =>
    setSelected(
      rows
        .filter((i) => !reasonFor(i))
        .slice(0, 100)
        .map((i) => i.id),
    );
  const nameFor = (id: string) => {
    const inv = invitations.find((i) => i.id === id);
    return inv?.guest_name_ar || inv?.guest_name || "دعوة";
  };
  return {
    visible,
    canSend,
    canView,
    canManage,
    canEditMessage,
    editorOpen,
    setEditorOpen,
    preview: { ...preview, data: previewData },
    previewImageReady: !previewData?.image_id || previewImage.isSuccess,
    eventId,
    conn,
    summary,
    filter,
    setFilter,
    selected,
    setSelected,
    selectedInvitations,
    confirm,
    setConfirm,
    resend,
    setResend,
    feedback,
    setFeedback,
    excluded,
    historyScope,
    setHistoryScope,
    history,
    historySearch,
    setHistorySearch,
    historyState,
    setHistoryState,
    historyPurpose,
    setHistoryPurpose,
    historyLimit,
    setHistoryLimit,
    navigateHistory,
    refreshHistory,
    offset,
    setOffset,
    send,
    cancel,
    review,
    busy,
    statusFor,
    currentDelivery,
    deliveries,
    reasonFor,
    matchesFilter,
    toggle,
    selectRows,
    openHistory,
    attempt,
    invalidate,
    reasonLabel,
    nameFor,
  };
}
export type WhatsAppTableController = ReturnType<typeof useWhatsAppTable>;
export type { DeliverySummary };
