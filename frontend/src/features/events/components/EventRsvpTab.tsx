import { useWhatsAppTable } from '@features/whatsapp/useWhatsAppTable'
import { WhatsAppTableFilter, WhatsAppTableToolbar, WhatsAppTableDialogs, WhatsAppSelection, WhatsAppStatusCell } from '@features/whatsapp/WhatsAppTable'
/**
 * EventRsvpTab.tsx
 * Tab for Event RSVP Management inside EventDetailsPage.
 * Shows stats, filters, manual updates, and CSV exports.
 */
import { useState, useMemo, useRef } from 'react'
import {
  Search, Users, CheckCircle2, XCircle, Clock,
  UserPlus, Download, Loader2,
  Eye, Send, Copy, CircleHelp, X
} from 'lucide-react'
import { useUpdateInvitation } from '@features/invitations/hooks/useInvitations'
import type { RsvpStatus, TicketClass, Invitation } from '@features/invitations/types'
import { RsvpDetailPanel } from './RsvpDetailPanel'
import { useInvitationTable } from '@features/invitations/hooks/useInvitationTable'
import { TablePagination } from '../../../components/TablePagination'
import './event-rsvp-tab.css'
import { getApiErrorMessage } from '@services/http/client'
import { Can, PERM } from '@shared/permissions'

interface Props {
  eventId: string
  allowRsvp?: boolean
  eventTitle?: string
}

export function EventRsvpTab({ eventId, eventTitle }: Props) {
  const helpRef = useRef<HTMLDetailsElement>(null)
  const [search, setSearch] = useState('')
  const [whatsappFilter,setWhatsappFilter] = useState('all')
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [rsvpFilter, setRsvpFilter] = useState<string>('all')
  const [classFilter, setClassFilter] = useState<TicketClass | 'all'>('all')
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [selectedInv, setSelectedInv] = useState<Invitation | null>(null)

  const page = useInvitationTable({event_id:eventId,tab:'rsvp',search,ticket_class:classFilter,rsvp_status:rsvpFilter,whatsapp_state:whatsappFilter})
  const invitations = page.items
  const rsvpInvitations = page.items
  const stats = page.stats
  const refetch = page.query.refetch
  const wa = useWhatsAppTable(eventId,rsvpInvitations,{page:page.query,filter:whatsappFilter,setFilter:setWhatsappFilter,scope:JSON.stringify(page.params),searching:page.searching})
  const isRsvpMode = true

  const activeSelectedInv = useMemo(() => {
    if (!selectedInv || !rsvpInvitations) return null
    return rsvpInvitations.find((i) => i.id === selectedInv.id) || null
  }, [selectedInv, rsvpInvitations])

  const updateMutation = useUpdateInvitation()

  const filtered = rsvpInvitations
  const handleExportCSV = () => page.exportRows.mutate()

  // ── Manual RSVP Update ──
  const handleManualRsvp = async (
    id: string,
    status: RsvpStatus,
    plusOneCount?: number,
    messageText?: string | null,
    guestCount?: number
  ) => {
    setUpdatingId(id)
    setActionError(null)
    try {
      const invStatus = status === 'accepted' ? 'accepted' : (status === 'declined' ? 'declined' : 'created')
      
      // Preserve existing parameters if not explicitly provided
      const current = invitations?.find(i => i.id === id)
      const pCount = plusOneCount !== undefined ? plusOneCount : (status === 'accepted' ? (current?.plus_one_count || 0) : 0)
      const msg = messageText !== undefined ? messageText : (current?.rsvp_message || null)
      const gCount = guestCount !== undefined ? guestCount : (current?.guest_count || 1)

      await updateMutation.mutateAsync({
        id,
        data: {
          rsvp_status: status,
          status: invStatus,
          plus_one_count: pCount,
          rsvp_message: msg,
          guest_count: gCount,
          rsvp_at: status === 'pending' ? null : new Date().toISOString()
        }
      })
    } catch (err) {
      setActionError(getApiErrorMessage(err, 'لم يتم حفظ الرد. حاول مجدداً.'))
    } finally {
      setUpdatingId(null)
    }
  }


  return (
    <div className="rsvp-tab-content">
      {actionError && <p role="alert" style={{ color: 'var(--color-danger, #b91c1c)' }}>{actionError}</p>}
      {page.query.isError && <p role="alert" className="wa-error">{getApiErrorMessage(page.query.error)} <button className="btn btn-secondary" onClick={() => refetch()}>إعادة المحاولة</button></p>}
      {page.exportRows.isError && <p role="alert" className="wa-error">{getApiErrorMessage(page.exportRows.error)}</p>}
      {/* ── Metric Cards ── */}
      <div className="rsvp-metrics-grid">
        <div className="rsvp-metric-card">
          <div className="rsvp-metric-card__header">
            <Users size={18} style={{ color: 'var(--color-primary)' }} />
            <span>إجمالي الدعوات</span>
          </div>
          <strong>{stats.total}</strong>
        </div>

        {isRsvpMode ? (
          <>
            <div className="rsvp-metric-card rsvp-metric-card--accepted">
              <div className="rsvp-metric-card__header">
                <CheckCircle2 size={18} style={{ color: '#10b981' }} />
                <span>حضور مؤكد</span>
              </div>
              <strong>{stats.accepted}</strong>
            </div>
            <div className="rsvp-metric-card rsvp-metric-card--declined">
              <div className="rsvp-metric-card__header">
                <XCircle size={18} style={{ color: '#ef4444' }} />
                <span>اعتذروا عن الحضور</span>
              </div>
              <strong>{stats.declined}</strong>
            </div>
            <div className="rsvp-metric-card rsvp-metric-card--pending">
              <div className="rsvp-metric-card__header">
                <Clock size={18} style={{ color: '#94a3b8' }} />
                <span>بانتظار الرد</span>
              </div>
              <strong>{stats.pending}</strong>
            </div>
            <div className="rsvp-metric-card">
              <div className="rsvp-metric-card__header">
                <UserPlus size={18} style={{ color: '#3b82f6' }} />
                <span>المرافقين (Plus-One)</span>
              </div>
              <strong>{stats.plusOnes}</strong>
            </div>
          </>
        ) : (
          <>
            <div className="rsvp-metric-card rsvp-metric-card--accepted">
              <div className="rsvp-metric-card__header">
                <Eye size={18} style={{ color: '#10b981' }} />
                <span>تمت المشاهدة</span>
              </div>
              <strong>{stats.viewed}</strong>
            </div>
            <div className="rsvp-metric-card" style={{ borderLeft: '4px solid #3b82f6' }}>
              <div className="rsvp-metric-card__header">
                <Send size={18} style={{ color: '#3b82f6' }} />
                <span>تم الإرسال والتسليم</span>
              </div>
              <strong>{stats.sent}</strong>
            </div>
            <div className="rsvp-metric-card rsvp-metric-card--pending">
              <div className="rsvp-metric-card__header">
                <Clock size={18} style={{ color: '#94a3b8' }} />
                <span>لم تفتح بعد</span>
              </div>
              <strong>{stats.unopened}</strong>
            </div>
          </>
        )}
      </div>

      {/* ── Filters and Actions Toolbar ── */}
      <div className="rsvp-toolbar-panel">
        <div className="rsvp-search-box">
          <Search size={16} />
          <input
            type="text"
            placeholder="بحث بالاسم أو الهاتف..."
            value={search}
            disabled={wa.busy}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="rsvp-filters-row">
          <details className="rsvp-help" ref={helpRef} onKeyDown={event => {
            if (event.key === 'Escape' && helpRef.current) {
              helpRef.current.open = false
              helpRef.current.querySelector('summary')?.focus()
            }
          }}>
            <summary className="rsvp-help-button"><CircleHelp size={15} />طريقة الاستخدام</summary>
            <div className="rsvp-help-panel">
              <div className="rsvp-help-heading">
                <strong>مشاركة الدعوات ومتابعة الردود</strong>
                <button type="button" aria-label="إغلاق طريقة الاستخدام" onClick={() => {
                  if (helpRef.current) {
                    helpRef.current.open = false
                    helpRef.current.querySelector('summary')?.focus()
                  }
                }}><X size={16} /></button>
              </div>
              <ol>
                <li>شارك رابط الضيف من إجراءات الصف، أو أرسل عبر WhatsApp عند تفعيل الخدمة.</li>
                <li>يؤكد الضيف حضوره أو يعتذر من الرابط دون تسجيل دخول.</li>
                <li>تابع الردود هنا، وتجد الموافقين في «الدعوات الجاهزة للدخول». ويمكن تسجيل الرد يدوياً.</li>
              </ol>
              <p>الدعوات التي تشترط التأكيد تتيح الدخول بعد الموافقة. يُسجّل الحضور الفعلي عند المسح في البوابة.</p>
            </div>
          </details>
          <WhatsAppTableFilter wa={wa} />
          <select
            value={rsvpFilter}
            aria-label="حالة تأكيد الحضور" disabled={wa.busy}
            onChange={(e) => setRsvpFilter(e.target.value as any)}
            className="rsvp-filter-dropdown"
          >
            {isRsvpMode ? (
              <>
                <option value="all">كل حالات الرد</option>
                <option value="accepted">مؤكد الحضور</option>
                <option value="declined">المعتذرين</option>
                <option value="pending">بانتظار الرد</option>
              </>
            ) : (
              <>
                <option value="all">كل الحالات (المشاهدة)</option>
                <option value="viewed">تمت المشاهدة</option>
                <option value="sent">تم الإرسال</option>
                <option value="created">لم ترسل بعد</option>
              </>
            )}
          </select>

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

          <Can permission={PERM.RSVP_EXPORT}>
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

      {/* ── RSVP List Table ── */}
      {page.query.isLoading || page.searching ? (<div className="rsvp-loading" aria-live="polite"><Loader2 size={26} className="spin" />جارٍ تحميل النتائج…</div>) : filtered.length === 0 ? (
        <div className="rsvp-empty-state">
          <Users size={40} style={{ opacity: 0.3 }} />
          <h4>لا توجد نتائج تطابق خيارات التصفية</h4>
          <p>تأكد من كتابة الاسم بشكل صحيح أو تغيير خيارات التصفية.</p>
        </div>
      ) : (
        <div className="rsvp-table-container">
          <table className="rsvp-table">
            <thead>
              {isRsvpMode ? (
                <tr>
                  {wa.visible && wa.canSend && <th className="wa-selection-column"><WhatsAppSelection wa={wa} rows={filtered} /></th>}
                  <th>الاسم</th>
                  <th>الهاتف</th>
                  {wa.visible && wa.canView && <th>WhatsApp</th>}
                  <th>فئة التذكرة</th>
                  <th>رد الضيف</th>
                  <th>المرافقين</th>
                  <th>تاريخ الرد</th>
                  <th>رسالة الضيف</th>
                  <th>إجراءات يدوية</th>
                </tr>
              ) : (
                <tr>
                  {wa.visible && wa.canSend && <th className="wa-selection-column"><WhatsAppSelection wa={wa} rows={filtered} /></th>}
                  <th>الاسم</th>
                  <th>الهاتف</th>
                  {wa.visible && wa.canView && <th>WhatsApp</th>}
                  <th>فئة التذكرة</th>
                  <th>حالة الدعوة</th>
                  <th>تاريخ الفتح والمشاهدة</th>
                  <th>قراءة الباركود</th>
                  <th>إجراءات سريعة</th>
                </tr>
              )}
            </thead>
            <tbody>
              {filtered.map((inv) => {
                const status = inv.rsvp_status || 'pending'
                const isOpened = inv.status === 'viewed' || inv.status === 'accepted' || inv.status === 'declined' || inv.status === 'checked_in'
                const isSent = inv.status === 'sent'

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

                    {isRsvpMode ? (
                      <>
                        <td>
                          <span className={`rsvp-status-badge rsvp-status-badge--${status}`}>
                            {status === 'accepted' ? 'أكد الحضور' : status === 'declined' ? 'اعتذر عن الحضور' : 'بانتظار الرد'}
                          </span>
                        </td>
                        <td className="rsvp-td-center">
                          {status === 'accepted' ? inv.plus_one_count || 0 : <span className="rsvp-txt-muted">—</span>}
                        </td>
                        <td>
                          {inv.rsvp_at ? (
                            <span className="rsvp-date-txt">
                              {new Date(inv.rsvp_at).toLocaleDateString('ar-SA')}
                            </span>
                          ) : (
                            <span className="rsvp-txt-muted">—</span>
                          )}
                        </td>
                        <td className="rsvp-td-message" title={inv.rsvp_message || ''}>
                          {inv.rsvp_message ? (
                            <span>{inv.rsvp_message}</span>
                          ) : (
                            <span className="rsvp-txt-muted">—</span>
                          )}
                        </td>
                        <td>
                          <div className="rsvp-action-btns">
                            <button className="rsvp-action-icon" title={copiedId === inv.id ? 'تم نسخ الرابط' : 'نسخ رابط تأكيد الحضور'} aria-label="نسخ رابط تأكيد الحضور" onClick={async (e) => {
                              e.stopPropagation()
                              try {
                                await navigator.clipboard.writeText(`${window.location.origin}/i/${inv.token}`)
                                setActionError(null)
                                setCopiedId(inv.id)
                                setTimeout(() => setCopiedId(null), 2000)
                              } catch { setActionError('تعذر نسخ الرابط. افتح تفاصيل الضيف لنسخه يدوياً.') }
                            }}>{copiedId === inv.id ? <CheckCircle2 size={15} /> : <Copy size={15} />}</button>
                            {updatingId === inv.id ? (
                              <Loader2 size={16} className="spin" style={{ color: 'var(--color-primary)' }} />
                            ) : (
                              <Can permission={PERM.RSVP_UPDATE}>
                              <>
                                {status !== 'accepted' && (
                                  <button
                                    className="rsvp-action-icon rsvp-action-icon--accept"
                                    onClick={(e) => { e.stopPropagation(); handleManualRsvp(inv.id, 'accepted'); }}
                                    title="تأكيد حضور الضيف يدوياً"
                                  >
                                    <CheckCircle2 size={15} />
                                  </button>
                                )}
                                {status !== 'declined' && (
                                  <button
                                    className="rsvp-action-icon rsvp-action-icon--decline"
                                    onClick={(e) => { e.stopPropagation(); handleManualRsvp(inv.id, 'declined'); }}
                                    title="تسجيل اعتذار الضيف يدوياً"
                                  >
                                    <XCircle size={15} />
                                  </button>
                                )}
                                {status !== 'pending' && (
                                  <button
                                    className="rsvp-action-icon rsvp-action-icon--reset"
                                    onClick={(e) => { e.stopPropagation(); handleManualRsvp(inv.id, 'pending'); }}
                                    title="إعادة تعيين وبانتظار الرد"
                                  >
                                    <Clock size={15} />
                                  </button>
                                )}
                              </>
                              </Can>
                            )}
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>
                          {isOpened ? (
                            <span className="rsvp-status-badge rsvp-status-badge--accepted">
                              تمت المشاهدة
                            </span>
                          ) : isSent ? (
                            <span className="rsvp-status-badge rsvp-status-badge--pending" style={{ color: '#3b82f6', background: 'rgba(59, 130, 246, 0.08)', borderColor: 'rgba(59, 130, 246, 0.15)' }}>
                              تم الإرسال
                            </span>
                          ) : (
                            <span className="rsvp-status-badge rsvp-status-badge--pending">
                              لم ترسل بعد
                            </span>
                          )}
                        </td>
                        <td>
                          {isOpened ? (
                            <span className="rsvp-date-txt">
                              {new Date(inv.updated_at).toLocaleDateString('ar-SA')} {new Date(inv.updated_at).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          ) : (
                            <span className="rsvp-txt-muted">—</span>
                          )}
                        </td>
                        <td>
                          {inv.checkin_count > 0 ? (
                            <span className="rsvp-status-badge rsvp-status-badge--accepted" style={{ background: 'rgba(16, 185, 129, 0.08)', color: '#10b981', borderColor: 'rgba(16, 185, 129, 0.15)' }}>
                              تم الدخول ({inv.checkin_count})
                            </span>
                          ) : (
                            <span className="rsvp-status-badge rsvp-status-badge--pending" style={{ color: '#94a3b8', background: 'rgba(148, 163, 184, 0.08)', borderColor: 'rgba(148, 163, 184, 0.15)' }}>
                              لم يحضر
                            </span>
                          )}
                        </td>
                        <td>
                          <div className="rsvp-action-btns">
                            <button
                              className="rsvp-action-icon"
                              onClick={(e) => {
                                e.stopPropagation();
                                navigator.clipboard.writeText(`${window.location.origin}/i/${inv.token}`);
                              }}
                              title="نسخ رابط بطاقة الدعوة للضيف"
                            >
                              <Copy size={15} />
                            </button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <TablePagination total={page.total} offset={page.offset} limit={page.limit} onOffset={page.setOffset} onLimit={page.setLimit} disabled={wa.busy || page.query.isLoading || page.searching} />

      <WhatsAppTableDialogs wa={wa} invitations={rsvpInvitations} eventTitle={eventTitle} />

      {/* ── Guest RSVP Detail Side Panel ── */}
      <RsvpDetailPanel
        invitation={activeSelectedInv}
        onClose={() => setSelectedInv(null)}
        onUpdateRsvp={handleManualRsvp}
        isUpdating={updatingId !== null}
        allowRsvp={isRsvpMode}
      />
    </div>
  )
}
