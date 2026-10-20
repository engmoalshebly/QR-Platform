import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CheckCheck,
  Check,
  Clock3,
  MessageCircle,
  Send,
  RefreshCw,
  X,
  Loader2,
  AlertCircle,
  SlidersHorizontal,
} from "lucide-react";
import type { Invitation } from "@features/invitations/types";
import { getApiErrorMessage } from "@services/http/client";
import { stateLabel, reasonLabel } from "./api";
import {
  deliveryLabels,
  purposeLabel,
  messagePurpose,
  type WhatsAppTableController,
} from "./useWhatsAppTable";
import { TablePagination } from "../../components/TablePagination";
import "./whatsapp.css";
import { WhatsAppMessageEditor, MessageImage } from "./WhatsAppMessageEditor";

export function WhatsAppTableFilter({ wa }: { wa: WhatsAppTableController }) {
  if (!wa.visible || !wa.canView) return null;
  return (
    <>
      <select
        className="rsvp-filter-dropdown"
        aria-label="حالة إرسال WhatsApp"
        value={wa.filter}
        disabled={wa.busy}
        onChange={(e) => wa.setFilter(e.target.value)}
      >
        <option value="all">كل حالات WhatsApp</option>
        <option value="not_sent">لم تُرسل</option>
        <option value="sent">تم الإرسال أو التسليم</option>
        <option value="delivered">تم التسليم</option>
        <option value="read">تمت القراءة</option>
        <option value="pending">في الطابور أو جارٍ الإرسال</option>
        <option value="failed">فشل الإرسال</option>
        <option value="unknown">تحتاج مراجعة</option>
        <option value="cancelled">أُلغي الإرسال</option>
      </select>
      <button
        className="btn btn-ghost wa-history-button"
        onClick={() => wa.openHistory()}
      >
        <Clock3 size={15} />
        سجل الإرسال
      </button>
    </>
  );
}
export function WhatsAppTableToolbar({
  wa,
  rows,
}: {
  wa: WhatsAppTableController;
  rows: Invitation[];
}) {
  const eligibleIds = rows
    .filter((i) => !wa.reasonFor(i))
    .map((i) => i.id)
    .join(",");
  useEffect(() => {
    if (wa.busy) return;
    const allowed = new Set(eligibleIds.split(","));
    wa.setSelected((previous) => {
      const next = previous.filter((id) => allowed.has(id));
      return next.length === previous.length ? previous : next;
    });
  }, [eligibleIds, wa.busy, wa.setSelected]);
  if (!wa.visible) return null;
  return (
    <div className="wa-table-tools" dir="rtl">
      <div className="wa-table-tools__main">
        <MessageCircle size={19} />
        <div>
          <strong>
            {wa.selectedInvitations.length
              ? `${wa.selectedInvitations.length} ضيف محدد`
              : "الإرسال عبر WhatsApp"}
          </strong>
          <small>
            {wa.canSend
              ? "حدد من الصفحة الحالية • حتى 100 ضيف في الدفعة"
              : "متابعة إرسال الرسائل وتسليمها"}
          </small>
        </div>
      </div>
      <div className="wa-table-tools__actions">
        <span
          className={`wa-connection-dot ${wa.conn.data?.status === "ready" && wa.conn.data.enabled ? "wa-connection-dot--ready" : ""}`}
        >
          {wa.conn.data?.enabled
            ? stateLabel[wa.conn.data.status] || "تعذر التحقق"
            : "الإرسال معطّل"}
        </span>
        {wa.canManage &&
          (!wa.conn.data?.enabled || !wa.conn.data.configured) && (
            <Link to="/settings" className="btn btn-ghost">
              إعدادات الاتصال
            </Link>
          )}
        {wa.canEditMessage && (
          <button
            className="btn btn-ghost"
            disabled={wa.busy}
            onClick={() => wa.setEditorOpen(true)}
          >
            <SlidersHorizontal size={15} />
            تخصيص الرسالة
          </button>
        )}
        {wa.canSend && (
          <>
            {wa.canView && (
              <button
                className="btn btn-ghost"
                disabled={
                  wa.busy ||
                  !wa.summary.data ||
                  !rows.some(
                    (i) => wa.statusFor(i) === "not_sent" && !wa.reasonFor(i),
                  )
                }
                onClick={() =>
                  wa.selectRows(
                    rows.filter((i) => wa.statusFor(i) === "not_sent"),
                  )
                }
              >
                تحديد غير المرسلة
              </button>
            )}
            {!!wa.selected.length && (
              <button
                className="btn btn-ghost"
                disabled={wa.busy}
                onClick={() => wa.setSelected([])}
              >
                إلغاء التحديد
              </button>
            )}
            <button
              className="btn btn-primary"
              disabled={
                !wa.selectedInvitations.length ||
                wa.busy ||
                !wa.conn.data?.configured ||
                !wa.conn.data.enabled
              }
              onClick={() => {
                wa.setFeedback("");
                wa.setConfirm([...wa.selectedInvitations]);
                if (!wa.attempt.current) wa.setResend(false);
              }}
            >
              <Send size={16} />
              إرسال المحدد ({wa.selectedInvitations.length})
            </button>
          </>
        )}
      </div>
      {wa.summary.isError && (
        <div
          role="alert"
          className="wa-table-feedback wa-table-feedback--error"
        >
          تعذر تحديث حالات الإرسال.{" "}
          <button
            className="btn btn-ghost"
            onClick={() => wa.summary.refetch()}
          >
            إعادة المحاولة
          </button>
        </div>
      )}
      {wa.feedback && !wa.confirm && (
        <div role="status" className="wa-table-feedback">
          {wa.feedback}
          {wa.excluded.length > 0 && (
            <details>
              <summary>عرض الضيوف المستبعدين ({wa.excluded.length})</summary>
              <ul>
                {wa.excluded.map((item) => (
                  <li key={item.invitation_id}>
                    {wa.nameFor(item.invitation_id)}:{" "}
                    {reasonLabel[item.reason!] || "غير مؤهلة"}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
export function WhatsAppSelection({
  wa,
  inv,
  rows,
}: {
  wa: WhatsAppTableController;
  inv?: Invitation;
  rows?: Invitation[];
}) {
  if (!wa.visible || !wa.canSend) return null;
  const eligible = (rows || []).filter((i) => !wa.reasonFor(i));
  const selectedCount = eligible.filter((i) =>
    wa.selected.includes(i.id),
  ).length;
  const checked = inv
    ? wa.selected.includes(inv.id)
    : eligible.length > 0 && selectedCount === Math.min(eligible.length, 100);
  const reason = inv ? wa.reasonFor(inv) : "";
  return (
    <input
      className="wa-row-checkbox"
      type="checkbox"
      aria-label={
        inv
          ? `تحديد ${inv.guest_name_ar || inv.guest_name || "الضيف"}`
          : "تحديد الصفحة الحالية (حتى 100)"
      }
      title={
        reason || (inv ? "تحديد الضيف" : "تحديد الصفحة الحالية، حتى 100 ضيف")
      }
      ref={(node) => {
        if (node && !inv) node.indeterminate = selectedCount > 0 && !checked;
      }}
      checked={checked}
      disabled={
        wa.busy ||
        !!reason ||
        (!inv && !eligible.length) ||
        (!!inv && !checked && wa.selected.length >= 100)
      }
      onClick={(e) => e.stopPropagation()}
      onChange={() =>
        inv
          ? wa.toggle(inv.id)
          : checked
            ? wa.setSelected([])
            : wa.selectRows(eligible)
      }
    />
  );
}
function StateBadge({ state }: { state: string }) {
  const Icon = ["delivered", "read"].includes(state)
    ? CheckCheck
    : state === "sent"
      ? Check
      : ["unknown", "failed"].includes(state)
        ? AlertCircle
        : state === "not_sent"
          ? MessageCircle
          : Clock3;
  return (
    <span className={`wa-delivery-badge wa-delivery-badge--${state}`}>
      <Icon size={13} />
      {deliveryLabels[state] || stateLabel[state] || "تعذر التحقق"}
    </span>
  );
}
export function WhatsAppStatusCell({
  wa,
  inv,
}: {
  wa: WhatsAppTableController;
  inv: Invitation;
}) {
  if (!wa.visible || !wa.canView) return null;
  const delivery = wa.currentDelivery(inv);
  const other = wa.deliveries.get(
    `${inv.id}:${messagePurpose(inv) === "rsvp" ? "ticket" : "rsvp"}`,
  );
  return (
    <button
      type="button"
      className="wa-status-cell"
      onClick={(e) => {
        e.stopPropagation();
        wa.openHistory(inv.id);
      }}
      aria-label={`سجل WhatsApp للضيف ${inv.guest_name_ar || inv.guest_name || "ضيف"}`}
      title={
        delivery
          ? `${purposeLabel(delivery.purpose)} • ${new Date(delivery.updated_at).toLocaleString("ar", { timeZone: "Asia/Aden" })}${delivery.error_code ? ` • ${reasonLabel[delivery.error_code] || "راجع النتيجة"}` : ""}`
          : "عرض سجل إرسال هذا الضيف"
      }
    >
      <StateBadge state={wa.statusFor(inv)} />
      <small>{purposeLabel(messagePurpose(inv))}</small>
      {other && (
        <small className="wa-status-cell__previous">
          {purposeLabel(other.purpose)}: {deliveryLabels[other.state]}
        </small>
      )}
    </button>
  );
}
function Modal({
  open,
  title,
  onClose,
  busy = false,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  busy?: boolean;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    else if (!open && node.open) node.close();
  }, [open]);
  return (
    <dialog
      className="wa-modal"
      ref={dialog}
      dir="rtl"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      {open && (
        <>
          <header className="wa-modal__header">
            <h3>
              <MessageCircle size={20} />
              {title}
            </h3>
            <button
              aria-label="إغلاق"
              className="btn btn-ghost"
              disabled={busy}
              onClick={onClose}
            >
              <X size={19} />
            </button>
          </header>
          {children}
        </>
      )}
    </dialog>
  );
}
export function WhatsAppTableDialogs({
  wa,
  invitations,
  eventTitle: _eventTitle,
}: {
  wa: WhatsAppTableController;
  invitations: Invitation[];
  eventTitle?: string;
}) {
  const [editorBusy, setEditorBusy] = useState(false);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("sent");
  useEffect(() => {
    setReviewId(null);
    setNote("");
    setOutcome("sent");
  }, [wa.historyScope]);
  if (!wa.visible) return null;
  const recipients = wa.confirm || [];
  const rsvpCount = recipients.filter(
    (i) => messagePurpose(i) === "rsvp",
  ).length;
  const scopeName = wa.historyScope?.invitationId
    ? invitations.find((i) => i.id === wa.historyScope?.invitationId)
        ?.guest_name_ar ||
      invitations.find((i) => i.id === wa.historyScope?.invitationId)
        ?.guest_name
    : null;
  return (
    <>
      <Modal
        open={wa.editorOpen && wa.canEditMessage}
        title="تخصيص رسالة WhatsApp"
        busy={editorBusy}
        onClose={() => wa.setEditorOpen(false)}
      >
        <WhatsAppMessageEditor
          eventId={wa.eventId}
          onClose={() => wa.setEditorOpen(false)}
          onBusy={setEditorBusy}
        />
      </Modal>
      <Modal
        open={!!wa.confirm}
        title="تأكيد الإرسال عبر WhatsApp"
        busy={wa.send.isPending}
        onClose={() => wa.setConfirm(null)}
      >
        <div className="wa-modal__body">
          <p>
            إرسال إلى <strong>{recipients.length} ضيف</strong> من التحديد في
            الجدول.
          </p>
          <div className="wa-send-breakdown">
            {!!rsvpCount && <span>{rsvpCount} طلب تأكيد حضور</span>}
            {recipients.length > rsvpCount && (
              <span>{recipients.length - rsvpCount} رابط دعوة</span>
            )}
          </div>
          <div className="wa-message-preview">
            <strong>معاينة الرسالة</strong>
            {wa.preview.isLoading ? (
              <Loader2
                className="spin"
                aria-label="جارٍ تحميل معاينة الرسالة"
              />
            ) : wa.preview.isError ? (
              <p role="alert">
                {getApiErrorMessage(wa.preview.error)}{" "}
                <button
                  className="btn btn-ghost"
                  onClick={() => wa.preview.refetch()}
                >
                  إعادة تحميل المعاينة
                </button>
              </p>
            ) : (
              <>
                <MessageImage
                  eventId={wa.eventId}
                  imageId={wa.preview.data?.image_id || null}
                />
                {wa.preview.data?.samples.map((sample) => (
                  <div key={sample.purpose} className="wa-confirm-message">
                    <small>
                      {purposeLabel(sample.purpose)} — {sample.guest_name}
                    </small>
                    <p dir="auto">{sample.text}</p>
                  </div>
                ))}
                {!!wa.preview.data?.too_long && (
                  <p role="alert" className="wa-error">
                    نص {wa.preview.data.too_long} دعوة يتجاوز حد الرسالة. اختصر
                    الرسالة أو أزل الصورة قبل الإرسال.
                  </p>
                )}
              </>
            )}
            <small>
              لكل ضيف اسمه ورابطه الخاص. هذه معاينة للنص المحفوظ؛ الصورة والنص
              يُرسلان في رسالة واحدة.
            </small>
          </div>
          <label className="wa-check">
            <input
              type="checkbox"
              checked={wa.resend}
              disabled={wa.send.isPending || !!wa.attempt.current}
              onChange={(e) => wa.setResend(e.target.checked)}
            />
            إعادة إرسال الرسائل المرسلة سابقاً من النوع نفسه
          </label>
          <small className="wa-muted">
            يُتجاوز من سبق الإرسال إليه ما لم تختر إعادة الإرسال. الرسائل
            الجارية والنتائج التي تحتاج مراجعة لا تُرسل مرة أخرى.
          </small>
          {wa.feedback && (
            <p role="alert" className="wa-error">
              {wa.feedback}
            </p>
          )}
        </div>
        <footer className="wa-modal__footer">
          <button
            className="btn btn-secondary"
            disabled={wa.send.isPending}
            onClick={() => wa.setConfirm(null)}
          >
            رجوع للجدول
          </button>
          <button
            className="btn btn-primary"
            disabled={
              wa.send.isPending ||
              !wa.canSend ||
              !wa.preview.data ||
              !wa.previewImageReady ||
              wa.preview.isError ||
              !!wa.preview.data?.too_long
            }
            onClick={() => wa.send.mutate()}
          >
            {wa.send.isPending ? (
              <Loader2 className="spin" size={17} />
            ) : (
              <Send size={17} />
            )}
            إرسال إلى {recipients.length} ضيف
          </button>
        </footer>
      </Modal>
      <Modal
        open={!!wa.historyScope && wa.canView}
        title={scopeName ? `سجل الإرسال — ${scopeName}` : "سجل الإرسال"}
        busy={wa.review.isPending}
        onClose={() => wa.setHistoryScope(null)}
      >
        <div className="wa-modal__body">
          <div className="wa-heading">
            <small>أحدث المحاولات • توقيت عدن</small>
            <button
              className="btn btn-ghost"
              onClick={wa.refreshHistory}
              disabled={wa.history.isFetching}
            >
              <RefreshCw size={15} />
              تحديث
            </button>
          </div>
          <div className="wa-history-filters">
            <input
              aria-label="البحث في سجل الإرسال"
              placeholder="بحث بالاسم أو رقم المستلم…"
              value={wa.historySearch}
              onChange={(e) => wa.setHistorySearch(e.target.value)}
            />
            <select
              aria-label="حالة الرسالة في السجل"
              value={wa.historyState}
              onChange={(e) => wa.setHistoryState(e.target.value)}
            >
              <option value="all">كل الحالات</option>
              {Object.entries(deliveryLabels)
                .filter(
                  ([key]) =>
                    !["not_sent", "loading", "unavailable"].includes(key),
                )
                .map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
            </select>
            <select
              aria-label="نوع الرسالة في السجل"
              value={wa.historyPurpose}
              onChange={(e) => wa.setHistoryPurpose(e.target.value)}
            >
              <option value="all">كل أنواع الرسائل</option>
              <option value="rsvp">طلب تأكيد حضور</option>
              <option value="ticket">رابط دعوة</option>
            </select>
          </div>
          {wa.history.isLoading ? (
            <Loader2 className="spin" />
          ) : wa.history.isError ? (
            <p role="alert">{getApiErrorMessage(wa.history.error)}</p>
          ) : (
            <div className="wa-table-wrap">
              <table className="wa-table">
                <thead>
                  <tr>
                    <th>الضيف</th>
                    <th>الرسالة</th>
                    <th>الحالة</th>
                    <th>التاريخ</th>
                    <th>الإجراء</th>
                  </tr>
                </thead>
                <tbody>
                  {wa.history.data?.items.map((d) => (
                    <tr key={d.id}>
                      <td>
                        {d.guest_name}
                        <small dir="ltr">{d.recipient}</small>
                      </td>
                      <td>{purposeLabel(d.purpose)}</td>
                      <td>
                        <StateBadge state={d.state} />
                        {d.error_code && (
                          <small>
                            {reasonLabel[d.error_code] || "راجع نتيجة المحاولة"}
                          </small>
                        )}
                      </td>
                      <td>
                        {new Date(d.created_at).toLocaleString("ar", {
                          timeZone: "Asia/Aden",
                        })}
                      </td>
                      <td>
                        {wa.canManage && d.state === "unknown" && (
                          <button
                            className="btn btn-secondary"
                            onClick={() => {
                              setReviewId(d.id);
                              setNote("");
                            }}
                          >
                            مراجعة النتيجة
                          </button>
                        )}
                        {wa.canSend &&
                          ["queued", "waiting_connection"].includes(
                            d.state,
                          ) && (
                            <button
                              className="btn btn-secondary"
                              disabled={wa.cancel.isPending}
                              onClick={() => wa.cancel.mutate(d.id)}
                            >
                              إلغاء الإرسال
                            </button>
                          )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!wa.history.data?.items.length && (
                <p className="wa-history-empty">
                  لا توجد محاولات إرسال في هذه الصفحة.
                </p>
              )}
            </div>
          )}
          {reviewId && wa.canManage && (
            <form
              className="wa-review"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await wa.review.mutateAsync({ id: reviewId, outcome, note });
                  setReviewId(null);
                } catch {
                  /* Mutation exposes the API error. */
                }
              }}
            >
              <h4>مراجعة نتيجة الإرسال</h4>
              <p>
                تحقق من هاتف المؤسسة ثم سجّل النتيجة والدليل قبل إعادة الإرسال.
              </p>
              <select
                aria-label="نتيجة مراجعة الإرسال"
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
                disabled={wa.review.isPending}
              >
                <option value="sent">ثبت إرسال الرسالة</option>
                <option value="not_sent">ثبت عدم إرسال الرسالة</option>
              </select>
              <textarea
                aria-label="دليل مراجعة الإرسال"
                placeholder="اكتب دليل التحقق (20 حرفاً على الأقل)"
                value={note}
                maxLength={500}
                onChange={(e) => setNote(e.target.value)}
                disabled={wa.review.isPending}
              />
              <div className="wa-actions">
                <button
                  className="btn btn-primary"
                  disabled={wa.review.isPending || note.trim().length < 20}
                >
                  حفظ المراجعة
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={wa.review.isPending}
                  onClick={() => setReviewId(null)}
                >
                  إلغاء
                </button>
              </div>
            </form>
          )}
          {wa.feedback && (
            <p role="status" className="wa-note">
              {wa.feedback}
            </p>
          )}
        </div>
        <footer className="wa-modal__footer">
          <TablePagination
            label="صفحات سجل الإرسال"
            total={wa.history.data?.total || 0}
            offset={wa.history.data?.offset ?? wa.offset}
            limit={wa.historyLimit}
            onOffset={wa.navigateHistory}
            onLimit={wa.setHistoryLimit}
            disabled={wa.history.isFetching || wa.review.isPending}
          />
        </footer>
      </Modal>
    </>
  );
}
