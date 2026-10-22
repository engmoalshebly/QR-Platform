import { useWhatsAppTable } from '@features/whatsapp/useWhatsAppTable'
import { WhatsAppTableFilter, WhatsAppTableToolbar, WhatsAppTableDialogs, WhatsAppSelection, WhatsAppStatusCell } from '@features/whatsapp/WhatsAppTable'
/**
 * EventFinalInvitationsTab.tsx
 * Tab for managing final confirmed invitations inside EventDetailsPage.
 * Shows only accepted invites (ready and allowed to enter).
 * Features rich metrics, search, ticket class and checkin status filters, and Excel export.
 */
import { useState, useMemo } from 'react'
import {
  Search, Users, Clock,
  Download, Loader2, RefreshCw,
  Eye, Copy, ShieldCheck, DoorOpen
} from 'lucide-react'
import { useUpdateInvitation } from '@features/invitations/hooks/useInvitations'
import type { RsvpStatus, TicketClass, Invitation } from '@features/invitations/types'
import { RsvpDetailPanel } from './RsvpDetailPanel'
import { useInvitationTable } from '@features/invitations/hooks/useInvitationTable'
import { TablePagination } from '../../../components/TablePagination'
import './event-rsvp-tab.css'
import { getApiErrorMessage } from '@services/http/client'
import { Can, PERM } from '@shared/permissions' // Reuse the same luxury CSS styling

interface Props {
  event: {
    id: string
    title: string
  }
  stats?: any
}

export function EventFinalInvitationsTab({ event }: Props) {
  const eventId = event.id
  const [search, setSearch] = useState('')
  const [whatsappFilter,setWhatsappFilter] = useState('all')
  const [classFilter, setClassFilter] = useState<TicketClass | 'all'>('all')
  const [checkinFilter, setCheckinFilter] = useState<'all' | 'checked_in' | 'not_checked_in'>('all')
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [selectedInv, setSelectedInv] = useState<Invitation | null>(null)

  const page = useInvitationTable({event_id:eventId,tab:'final',search,ticket_class:classFilter,checkin:checkinFilter,whatsapp_state:whatsappFilter})
  const finalInvitations = page.items
  const stats = page.stats
  const refetch = page.query.refetch
  const wa = useWhatsAppTable(eventId,finalInvitations,{page:page.query,filter:whatsappFilter,setFilter:setWhatsappFilter,scope:JSON.stringify(page.params),searching:page.searching})

  const activeSelectedInv = useMemo(() => {
    if (!selectedInv || !finalInvitations) return null
    return finalInvitations.find((i) => i.id === selectedInv.id) || null
  }, [selectedInv, finalInvitations])

  const updateMutation = useUpdateInvitation()

  const filtered = finalInvitations
  const handleExportCSV = () => page.exportRows.mutate()

  // ── Manual scan count update inside drawer panel ──
  const handleManualRsvp = async (
    id: string,
    status: RsvpStatus,
    plusOneCount?: number,
    messageText?: string | null,
    guestCount?: number
  ) => {
    setUpdatingId(id)
    try {
      const current = finalInvitations?.find(i => i.id === id)
      const pCount = plusOneCount !== undefined ? plusOneCount : (current?.plus_one_count || 0)
      const msg = messageText !== undefined ? messageText : (current?.rsvp_message || null)
      const gCount = guestCount !== undefined ? guestCount : (current?.guest_count || 1)

      await updateMutation.mutateAsync({
        id,
        data: {
          rsvp_status: status,
          status: status === 'accepted' ? 'accepted' : 'created',
          plus_one_count: pCount,
          rsvp_message: msg,
          guest_count: gCount,
        }
      })
    } catch {
      // Ignore errors
    } finally {
      setUpdatingId(null)
    }
  }


  return (
    <div className="rsvp-tab-content" dir="rtl">
      {page.query.isError && <p role="alert" className="wa-error">{getApiErrorMessage(page.query.error)} <button className="btn btn-secondary" onClick={() => refetch()}>إعادة المحاولة</button></p>}
      {page.exportRows.isError && <p role="alert" className="wa-error">{getApiErrorMessage(page.exportRows.error)}</p>}
      {/* ── Metric Cards ── */}
      <div className="rsvp-metrics-grid">
        <div className="rsvp-metric-card" style={{ borderLeft: '4px solid #D4A32C' }}>
          <div className="rsvp-metric-card__header">
            <ShieldCheck size={18} style={{ color: '#D4A32C' }} />
            <span>إجمالي الدعوات الجاهزة</span>
          </div>
          <strong>{stats.total}</strong>
        </div>

        <div className="rsvp-metric-card">
          <div className="rsvp-metric-card__header">
            <Users size={18} style={{ color: '#D4A32C' }} />
            <span>كبار الشخصيات VIP</span>
          </div>
          <strong>{stats.vip}</strong>
        </div>

        <div className="rsvp-metric-card">
          <div className="rsvp-metric-card__header">
            <Users size={18} style={{ color: '#94a3b8' }} />
            <span>دخول عادي</span>
          </div>
          <strong>{stats.normal}</strong>
        </div>

        <div className="rsvp-metric-card rsvp-metric-card--accepted">
          <div className="rsvp-metric-card__header">
            <DoorOpen size={18} style={{ color: '#10b981' }} />
            <span>تم حضورهم</span>
          </div>
          <strong>{stats.checkedIn}</strong>
        </div>

        <div className="rsvp-metric-card rsvp-metric-card--pending">
          <div className="rsvp-metric-card__header">
            <Clock size={18} style={{ color: '#94a3b8' }} />
            <span>بانتظار وصولهم</span>
          </div>
          <strong>{stats.remaining}</strong>
        </div>
      </div>

      {/* ── Filters and Actions Toolbar ── */}
      <div className="rsvp-toolbar-panel">
        <div className="rsvp-search-box">
          <Search size={16} />
          <input
            type="text"
            placeholder="بحث بالاسم أو الهاتف أو الرمز..."
            value={search}
            disabled={wa.busy}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="rsvp-filters-row">
          <WhatsAppTableFilter wa={wa} />
          <select
            value={classFilter}
            aria-label="فئة الدعوة" disabled={wa.busy}
            onChange={(e) => setClassFilter(e.target.value as any)}
            className="rsvp-filter-dropdown"
          >
            <option value="all">كل الفئات</option>
            <option value="vip">VIP</option>
            <option value="normal">عادي</option>
          </select>

          <select
            value={checkinFilter}
            aria-label="حالة الدخول" disabled={wa.busy}
            onChange={(e) => setCheckinFilter(e.target.value as any)}
            className="rsvp-filter-dropdown"
          >
            <option value="all">كل الحضور</option>
            <option value="checked_in">تم الدخول</option>
            <option value="not_checked_in">لم يحضر بعد</option>
          </select>

          <Can permission={PERM.INV_EXPORT}>
            <button
              className="btn btn-ghost"
              onClick={handleExportCSV}
              disabled={!page.total || page.query.isLoading || page.searching || page.exportRows.isPending}
            >
              <Download size={15} />
              <span>{page.exportRows.isPending ? 'جارٍ التصدير…' : 'تصدير النتائج'}</span>
            </button>
          </Can>
        </div>
      </div>

      <WhatsAppTableToolbar wa={wa} rows={filtered} />

      {/* ── Table List ── */}
      {page.query.isLoading || page.searching ? (<div className="rsvp-loading" aria-live="polite"><Loader2 size={26} className="spin" />جارٍ تحميل النتائج…</div>) : filtered.length === 0 ? (
        <div className="rsvp-empty-state">
          <Users size={40} style={{ opacity: 0.3 }} />
          <h4>لا توجد دعوات جاهزة مطابقة لخيارات البحث والتصفية</h4>
          <p>تأكد من إدخال اسم صحيح أو تعديل خيارات التصفية.</p>
        </div>
      ) : (
        <div className="rsvp-table-container">
          <table className="rsvp-table">
            <thead>
              <tr>
                {wa.visible && wa.canSend && <th className="wa-selection-column"><WhatsAppSelection wa={wa} rows={filtered} /></th>}
                  <th>الاسم الكامل</th>
                <th>الهاتف</th>
                  {wa.visible && wa.canView && <th>WhatsApp</th>}
                <th>فئة التذكرة</th>
                <th>حالة الدخول</th>
                <th>مرات القراءة</th>
                <th>الحد المسموح</th>
                <th>الباركود</th>
                <th>خيارات سريعة</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((inv) => {
                const isChecked = inv.checkin_count > 0
                return (
                  <tr key={inv.id} className={wa.selected.includes(inv.id) ? "wa-selected-row" : undefined} onClick={() => setSelectedInv(inv)}>
                    {wa.visible && wa.canSend && <td className="wa-selection-column"><WhatsAppSelection wa={wa} inv={inv} /></td>}
                    <td className="rsvp-td-name">
                      <strong>{inv.guest_name_ar || inv.guest_name || 'ضيف بدون اسم'}</strong>
                    </td>
                    <td dir="ltr">{inv.guest_whatsapp || inv.guest_phone || <span className="rsvp-txt-muted">—</span>}</td>
                    {wa.visible && wa.canView && <td><WhatsAppStatusCell wa={wa} inv={inv} /></td>}
                    <td>
                      <span className={`rsvp-class-badge rsvp-class-badge--${inv.ticket_class}`}>
                        {inv.ticket_class === 'vip' ? 'VIP' : 'عادي'}
                      </span>
                    </td>
                    <td>
                      {isChecked ? (
                        <span className="rsvp-status-badge rsvp-status-badge--accepted">
                          تم الدخول
                        </span>
                      ) : (
                        <span className="rsvp-status-badge rsvp-status-badge--pending">
                          لم يحضر بعد
                        </span>
                      )}
                    </td>
                    <td className="rsvp-td-center" style={{ fontWeight: 600 }}>
                      {inv.checkin_count || 0}
                    </td>
                    <td className="rsvp-td-center" style={{ opacity: 0.8 }}>
                      {inv.guest_count || 1}
                    </td>
                    <td>
                      <span className="rsvp-date-txt" style={{ fontFamily: 'monospace', opacity: 0.7 }}>
                        {inv.token}
                      </span>
                    </td>
                    <td>
                      <div className="rsvp-action-btns" onClick={(e) => e.stopPropagation()}>
                        {updatingId === inv.id ? (
                          <Loader2 size={15} className="spin" style={{ color: 'var(--color-primary)' }} />
                        ) : (
                          <>
                            {inv.metadata?.require_rsvp !== true && (
                              <button
                                className="rsvp-action-icon"
                                onClick={async () => {
                                  const phone = (inv.guest_phone || '').trim()
                                  const email = (inv.guest_email || '').trim()
                                  if (!phone && !email) {
                                    alert('لا يمكن تحويل الدعوة لطلب تأكيد الحضور لعدم وجود بيانات اتصال (رقم هاتف أو بريد إلكتروني) للضيف.')
                                    return
                                  }
                                  if (window.confirm(`هل أنت متأكد من تحويل الدعوة "${inv.guest_name_ar || inv.guest_name}" لطلب تأكيد الحضور ونقلها إلى تبويب ردود الضيوف؟`)) {
                                    setUpdatingId(inv.id);
                                    try {
                                      await updateMutation.mutateAsync({
                                        id: inv.id,
                                        data: {
                                          rsvp_status: 'pending',
                                          status: 'created',
                                          metadata: { ...inv.metadata, require_rsvp: true }
                                        }
                                      });
                                      refetch();
                                    } catch {
                                      void refetch()
                                    } finally {
                                      setUpdatingId(null);
                                    }
                                  }
                                }}
                                title="تحويل لطلب تأكيد الحضور ونقلها لقائمة تأكيد الحضور"
                                style={{ color: 'var(--color-primary)' }}
                              >
                                <RefreshCw size={15} />
                              </button>
                            )}
                            <button
                              className="rsvp-action-icon"
                              onClick={() => {
                                navigator.clipboard.writeText(`${window.location.origin}/i/${inv.token}`);
                                alert('تم نسخ رابط بطاقة الدعوة بنجاح!');
                              }}
                              title="نسخ رابط الدعوة للضيف"
                            >
                              <Copy size={15} />
                            </button>
                            <a
                              href={`/i/${inv.token}`}
                              target="_blank"
                              rel="noreferrer"
                              className="rsvp-action-icon"
                              title="عرض بطاقة الدعوة"
                            >
                              <Eye size={15} />
                            </a>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <TablePagination total={page.total} offset={page.offset} limit={page.limit} onOffset={page.setOffset} onLimit={page.setLimit} disabled={wa.busy || page.query.isLoading || page.searching} />

      <WhatsAppTableDialogs wa={wa} invitations={finalInvitations} eventTitle={event.title} />

      {/* Drawer Panel */}
      <RsvpDetailPanel
        invitation={activeSelectedInv}
        onClose={() => setSelectedInv(null)}
        onUpdateRsvp={handleManualRsvp}
        isUpdating={updatingId !== null}
        allowRsvp={false} // Disable RSVP state changes since these are finalized, but allow scan limits
      />
    </div>
  )
}
