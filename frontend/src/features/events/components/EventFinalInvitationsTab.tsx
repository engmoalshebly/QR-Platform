/**
 * EventFinalInvitationsTab.tsx
 * Tab for managing final confirmed invitations inside EventDetailsPage.
 * Shows only accepted invites (ready and allowed to enter).
 * Features rich metrics, search, ticket class and checkin status filters, and Excel export.
 */
import { useState, useMemo } from 'react'
import {
  Search, Users, Clock,
  Download, Loader2, RefreshCw, AlertCircle,
  Eye, Copy, ShieldCheck, DoorOpen
} from 'lucide-react'
import { useInvitationsList, useUpdateInvitation } from '@features/invitations/hooks/useInvitations'
import type { RsvpStatus, TicketClass, Invitation } from '@features/invitations/types'
import { RsvpDetailPanel } from './RsvpDetailPanel'
import './event-rsvp-tab.css'
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
  const [classFilter, setClassFilter] = useState<TicketClass | 'all'>('all')
  const [checkinFilter, setCheckinFilter] = useState<'all' | 'checked_in' | 'not_checked_in'>('all')
  const [updatingId, setUpdatingId] = useState<string | null>(null)
  const [selectedInv, setSelectedInv] = useState<Invitation | null>(null)

  // ── Data Query ──
  const { data: invitations, isLoading, isError, refetch } = useInvitationsList({
    event_id: eventId,
    limit: 500, // Fetch up to 500 invitations (backend maximum limit)
  })

  // ── Sync active selected invitation with updated refetched data ──
  const finalInvitations = useMemo(() => {
    if (!invitations) return []
    return invitations.filter((inv) => inv.rsvp_status === 'accepted')
  }, [invitations])

  const activeSelectedInv = useMemo(() => {
    if (!selectedInv || !finalInvitations) return null
    return finalInvitations.find((i) => i.id === selectedInv.id) || null
  }, [selectedInv, finalInvitations])

  const updateMutation = useUpdateInvitation()

  // ── Stats Calculations ──
  const stats = useMemo(() => {
    if (!finalInvitations) return { total: 0, vip: 0, normal: 0, checkedIn: 0, remaining: 0 }
    
    let vip = 0
    let normal = 0
    let checkedIn = 0

    finalInvitations.forEach((inv) => {
      if (inv.ticket_class === 'vip') vip++
      else normal++

      if (inv.checkin_count > 0) {
        checkedIn++
      }
    })

    return {
      total: finalInvitations.length,
      vip,
      normal,
      checkedIn,
      remaining: finalInvitations.length - checkedIn
    }
  }, [finalInvitations])

  // ── Search & Filter ──
  const filtered = useMemo(() => {
    if (!finalInvitations) return []
    return finalInvitations.filter((inv) => {
      // Search match
      const q = search.toLowerCase().trim()
      const matchesSearch = !q ||
        inv.guest_name?.toLowerCase().includes(q) ||
        inv.guest_name_ar?.includes(q) ||
        inv.guest_phone?.includes(q) ||
        inv.token?.includes(q)

      // Ticket Class Filter
      const matchesClass = classFilter === 'all' || inv.ticket_class === classFilter

      // Check-in Filter
      const isCheckedIn = inv.checkin_count > 0
      const matchesCheckin = checkinFilter === 'all' || 
        (checkinFilter === 'checked_in' && isCheckedIn) ||
        (checkinFilter === 'not_checked_in' && !isCheckedIn)

      return matchesSearch && matchesClass && matchesCheckin
    })
  }, [finalInvitations, search, classFilter, checkinFilter])

  // ── Export CSV ──
  const handleExportCSV = () => {
    if (!filtered || filtered.length === 0) return
    
    const headers = ["الاسم الكامل", "رقم الجوال", "فئة التذكرة", "حالة الدخول", "عدد مرات القراءة", "بوابة الدخول", "تاريخ وقبول الدعوة"]

    const rows = filtered.map(inv => {
      const isChecked = inv.checkin_count > 0
      const statusLabel = isChecked ? 'تم الدخول' : 'لم يحضر بعد'
      const acceptDate = inv.updated_at ? new Date(inv.updated_at).toLocaleString('ar-SA') : ''
      return [
        inv.guest_name_ar || inv.guest_name || '',
        inv.guest_phone || '',
        inv.ticket_class === 'vip' ? 'VIP' : 'عادي',
        statusLabel,
        inv.checkin_count || 0,
        inv.gate_id || 'تلقائي',
        acceptDate
      ]
    })
    
    // Excel-friendly UTF-8 BOM
    const csvContent = "\uFEFF" + [
      headers.map(h => `"${h}"`).join(','), 
      ...rows.map(r => r.map(val => `"${String(val).replace(/"/g, '""')}"`).join(','))
    ].join('\r\n')
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.setAttribute("href", url)
    link.setAttribute("download", `الدعوات_النهائية_المقبولة_${event.title}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

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

  if (isLoading) {
    return (
      <div className="rsvp-loading">
        <Loader2 size={36} className="spin" />
        <span>جاري تحميل قائمة المدعوين النهائيين...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rsvp-error">
        <AlertCircle size={40} />
        <h3>فشل تحميل القائمة</h3>
        <p>يرجى التحقق من اتصالك بالإنترنت وإعادة المحاولة.</p>
        <button className="btn btn-primary" onClick={() => refetch()}>
          <RefreshCw size={16} />
          إعادة المحاولة
        </button>
      </div>
    )
  }

  return (
    <div className="rsvp-tab-content" dir="rtl">
      {/* ── Metric Cards ── */}
      <div className="rsvp-metrics-grid">
        <div className="rsvp-metric-card" style={{ borderLeft: '4px solid #C9A96E' }}>
          <div className="rsvp-metric-card__header">
            <ShieldCheck size={18} style={{ color: '#C9A96E' }} />
            <span>إجمالي الدعوات الجاهزة</span>
          </div>
          <strong>{stats.total}</strong>
        </div>

        <div className="rsvp-metric-card">
          <div className="rsvp-metric-card__header">
            <Users size={18} style={{ color: '#C9A96E' }} />
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
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="rsvp-filters-row">
          <select
            value={classFilter}
            onChange={(e) => setClassFilter(e.target.value as any)}
            className="rsvp-filter-dropdown"
          >
            <option value="all">كل الفئات</option>
            <option value="vip">VIP</option>
            <option value="normal">عادي</option>
          </select>

          <select
            value={checkinFilter}
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
              disabled={filtered.length === 0}
            >
              <Download size={15} />
              <span>تصدير القائمة Excel</span>
            </button>
          </Can>
        </div>
      </div>

      {/* ── Table List ── */}
      {filtered.length === 0 ? (
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
                <th>الاسم الكامل</th>
                <th>الهاتف</th>
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
                  <tr key={inv.id} onClick={() => setSelectedInv(inv)}>
                    <td className="rsvp-td-name">
                      <strong>{inv.guest_name_ar || inv.guest_name || 'ضيف بدون اسم'}</strong>
                    </td>
                    <td>{inv.guest_phone || <span className="rsvp-txt-muted">—</span>}</td>
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
                                    alert('لا يمكن تحويل الدعوة لطلب RSVP لعدم وجود بيانات اتصال (رقم هاتف أو بريد إلكتروني) للضيف.')
                                    return
                                  }
                                  if (window.confirm(`هل أنت متأكد من تحويل الدعوة "${inv.guest_name_ar || inv.guest_name}" لطلب RSVP ونقلها لتاب تأكيد الحضور؟`)) {
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
                                title="تحويل لطلب RSVP ونقلها لقائمة تأكيد الحضور"
                                style={{ color: 'var(--color-primary)' }}
                              >
                                <RefreshCw size={15} />
                              </button>
                            )}
                            <button
                              className="rsvp-action-icon"
                              onClick={() => {
                                navigator.clipboard.writeText(`${window.location.origin}/i/${inv.token}`);
                                alert('تم نسخ رابط كرت الدعوة بنجاح!');
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
