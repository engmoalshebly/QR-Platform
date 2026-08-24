/**
 * EventApplicantsTab.tsx
 * Dedicated Premium Admin UI for managing self-registered applicants,
 * approval/decline workflow, CSV/Excel/PDF/ZIP exports, and registrant details drawer.
 */
import { useState, useMemo } from 'react'
import { Can, PERM } from '@shared/permissions'
import {
  ClipboardList,
  Download,
  Loader2,
  Search,
  Users,
  CheckCircle,
  XCircle,
  AlertCircle,
  Sparkles,
  X,
  QrCode,
  ExternalLink,
  User,
  Phone,
  Mail,
  Calendar,
  Settings,
  Edit3,
  Save
} from 'lucide-react'
import { downloadAuthenticatedFile } from '@services/http/client'
import { useInvitationsList, useUpdateInvitation } from '@features/invitations/hooks/useInvitations'
import { LocalQrCode } from '@shared/components/LocalQrCode'
import './event-registration.css'

interface Props {
  eventId: string
  eventTitle: string
  isActiveTab: boolean
}

export function EventApplicantsTab({ eventId, eventTitle, isActiveTab }: Props) {
  // ── States ──
  const [applicantStatusFilter, setApplicantStatusFilter] = useState<'all' | 'pending' | 'accepted' | 'declined'>('all')
  const [applicantSearch, setApplicantSearch] = useState('')

  // ── Selected Applicant Detail Drawer States ──
  const [selectedApplicant, setSelectedApplicant] = useState<any | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editPhone, setEditPhone] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editTicketClass, setEditTicketClass] = useState<'vip' | 'normal'>('normal')
  const [editCustomFields, setEditCustomFields] = useState<Record<string, any>>({})

  // ── Custom Alert State ──
  const [customAlert, setCustomAlert] = useState<{
    show: boolean
    title: string
    message: string
    type: 'success' | 'info' | 'error' | 'warning'
  }>({
    show: false,
    title: '',
    message: '',
    type: 'info'
  })

  const showAlert = (title: string, message: string, type: 'success' | 'info' | 'error' | 'warning' = 'info') => {
    setCustomAlert({
      show: true,
      title,
      message,
      type
    })
  }

  // ── Query List of Applicants for this specific event ──
  const { data: invitations, isLoading: isLoadingInvs, refetch: refetchInvs } = useInvitationsList({
    event_id: eventId,
    limit: 500
  })

  // ── Filter to get only registration form submissions ──
  const registeredGuests = useMemo(() => {
    if (!invitations) return []
    return invitations.filter(inv => {
      const isFromForm = !!inv.is_registration;
      return isFromForm && ['pending', 'accepted', 'declined'].includes(inv.rsvp_status || '');
    })
  }, [invitations])

  // ── Sort: Newest submissions at the top ──
  const sortedApplicants = useMemo(() => {
    return [...registeredGuests].sort((a, b) => {
      return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
    })
  }, [registeredGuests])



  // ── Filtered Applicants based on search and status filter ──
  const filteredApplicants = useMemo(() => {
    return sortedApplicants.filter(inv => {
      const status = inv.rsvp_status || '';
      
      const searchLower = applicantSearch.toLowerCase().trim()
      const nameMatch = !searchLower || 
        inv.guest_name?.toLowerCase().includes(searchLower) ||
        inv.guest_name_ar?.includes(searchLower) ||
        inv.guest_phone?.includes(searchLower);
        
      const statusMatch = applicantStatusFilter === 'all' || status === applicantStatusFilter;
      return nameMatch && statusMatch;
    })
  }, [sortedApplicants, applicantSearch, applicantStatusFilter])

  const updateMutation = useUpdateInvitation()

  // ── Actions Handlers ──
  const handleApproveApplicant = (invId: string) => {
    updateMutation.mutate({
      id: invId,
      data: { status: 'accepted', rsvp_status: 'accepted' }
    }, {
      onSuccess: () => {
        refetchInvs()
        showAlert('تم القبول بنجاح', 'تم قبول طلب التسجيل وتوليد الباركود وبطاقة الدخول بنجاح.', 'success')
      },
      onError: (err: any) => {
        showAlert('فشل القبول', `فشل قبول الطلب: ${err.message || err}`, 'error')
      }
    })
  }

  const handleDeclineApplicant = (invId: string) => {
    if (confirm('هل أنت متأكد من رفض هذا الطلب؟')) {
      updateMutation.mutate({
        id: invId,
        data: { status: 'declined', rsvp_status: 'declined' }
      }, {
        onSuccess: () => {
          refetchInvs()
          showAlert('تم الرفض بنجاح', 'تم رفض طلب التسجيل بنجاح.', 'success')
        },
        onError: (err: any) => {
          showAlert('فشل الرفض', `فشل رفض الطلب: ${err.message || err}`, 'error')
        }
      })
      return true
    }
    return false
  }

  const handleSaveApplicant = (id: string, updatedData: any) => {
    updateMutation.mutate({
      id,
      data: updatedData
    }, {
      onSuccess: () => {
        refetchInvs()
        setIsEditing(false)
        setSelectedApplicant((prev: any) => prev ? { ...prev, ...updatedData } : null)
        showAlert('تم التحديث بنجاح', 'تم تحديث بيانات المسجل بنجاح.', 'success')
      },
      onError: (err: any) => {
        showAlert('فشل التعديل', `فشل حفظ التعديلات: ${err.message || err}`, 'error')
      }
    })
  }

  const handleExportApplicants = () => {
    if (registeredGuests.length === 0) {
      showAlert('لا يوجد بيانات', 'لا يوجد مسجلين لتصديرهم حالياً.', 'warning')
      return
    }
    
    const headers = ["الاسم", "رقم الجوال", "البريد الإلكتروني", "الحالة", "تاريخ التسجيل", "الخيارات المخصصة"]
    const rows = registeredGuests.map(inv => {
      const answers = inv.metadata?.custom_fields
        ? Object.entries(inv.metadata.custom_fields)
            .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
            .join(' | ')
        : ''
      const statusTxt = inv.rsvp_status === 'accepted' ? 'مقبول' : (inv.rsvp_status === 'declined' ? 'مرفوض' : 'قيد الانتظار')
      return [
        inv.guest_name || inv.guest_name_ar || '',
        inv.guest_phone || '',
        inv.guest_email || '',
        statusTxt,
        inv.created_at ? new Date(inv.created_at).toLocaleString('ar-SA') : '',
        answers
      ]
    })
    
    const csvContent = "\uFEFF" + [
      headers.map(h => `"${h}"`).join(','),
      ...rows.map(r => r.map(val => `"${String(val).replace(/"/g, '""')}"`).join(','))
    ].join('\r\n')
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.setAttribute("href", url)
    link.setAttribute("download", `مسجلي_الحدث_${eventTitle}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  if (!isActiveTab) return null

  return (
    <div className="event-registration-tab-overhaul" dir="rtl" style={{ marginTop: 20 }}>


      {/* ── Main Panel View (No modal) ── */}
      <div className="glass-panel" style={{ padding: 24, borderRadius: 16, display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Toolbar: Search + Filter + Export */}
        <div className="applicants-modal-toolbar">
          <div style={{ display: 'flex', gap: 12, flex: 1, minWidth: '280px' }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <Search size={16} style={{ position: 'absolute', right: 12, top: 12, color: '#64748b' }} />
              <input
                type="text"
                placeholder="بحث باسم المسجل أو الهاتف..."
                value={applicantSearch}
                onChange={(e) => setApplicantSearch(e.target.value)}
                className="applicants-search-input"
                style={{ paddingRight: 36, width: '100%' }}
              />
            </div>
            <select
              value={applicantStatusFilter}
              onChange={(e) => setApplicantStatusFilter(e.target.value as any)}
              className="applicants-status-select"
            >
              <option value="all">جميع الحالات</option>
              <option value="pending">قيد الانتظار والمراجعة</option>
              <option value="accepted">المقبولين (تم إصدار كود)</option>
              <option value="declined">المرفوضين</option>
            </select>
          </div>
          
          <Can permission={PERM.BATCH_DOWNLOAD}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); void downloadAuthenticatedFile(`/fast-invitations/history/${eventId}/registration_submissions/pdf`, 'registration-submissions.pdf') }}
                target="_blank"
                rel="noreferrer"
                className="btn-export-excel"
                style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.2)', color: '#10b981', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <Download size={14} />
                <span>تنزيل PDF</span>
              </a>
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); void downloadAuthenticatedFile(`/fast-invitations/history/${eventId}/registration_submissions/zip`, 'registration-submissions.zip') }}
                target="_blank"
                rel="noreferrer"
                className="btn-export-excel"
                style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', color: '#3b82f6', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <Download size={14} />
                <span>تنزيل ZIP</span>
              </a>
              <button className="btn-export-excel" onClick={handleExportApplicants}>
                <Download size={14} />
                <span>تصدير Excel</span>
              </button>
            </div>
          </Can>
        </div>

        {/* Applicants Table */}
        {isLoadingInvs ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: '#9ca3af' }}>
            <Loader2 className="spin" size={28} style={{ color: '#C9A96E', margin: '0 auto 12px' }} />
            <span>جاري تحميل قائمة المسجلين...</span>
          </div>
        ) : sortedApplicants.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 20px', color: '#64748b' }}>
            <Users size={48} style={{ margin: '0 auto 16px', opacity: 0.5, color: '#C9A96E' }} />
            <h4 style={{ color: '#ffffff', fontSize: '1.1rem' }}>لا يوجد أي مسجلين لهذا الحدث بعد</h4>
            <p style={{ fontSize: '0.85rem', marginTop: 6, color: '#94a3b8' }}>بمجرد قيام الضيوف بالتسجيل عبر الرابط العام، ستظهر طلباتهم هنا.</p>
          </div>
        ) : filteredApplicants.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 20px', color: '#64748b' }}>
            <Search size={32} style={{ margin: '0 auto 12px', opacity: 0.5 }} />
            <h4 style={{ color: '#ffffff' }}>لا توجد نتائج مطابقة للبحث</h4>
            <p style={{ fontSize: '0.85rem', marginTop: 4 }}>يرجى تعديل نص البحث أو شروط الفلترة.</p>
          </div>
        ) : (
          <div className="table-container-glass">
            <table className="applicants-table">
              <thead>
                <tr>
                  <th>الاسم الكامل</th>
                  <th>رقم الجوال</th>
                  <th>البريد الإلكتروني</th>
                  <th>تاريخ التقديم</th>
                  <th>الحالة</th>
                  <th>إجراءات</th>
                </tr>
              </thead>
              <tbody>
                {filteredApplicants.map((inv) => {
                  const answers = inv.metadata?.custom_fields || {};
                  const hasAnswers = Object.keys(answers).length > 0;
                  
                  return (
                    <tr 
                      key={inv.id}
                      onClick={() => {
                        setSelectedApplicant(inv)
                        setEditName(inv.guest_name_ar || inv.guest_name || '')
                        setEditPhone(inv.guest_phone || '')
                        setEditEmail(inv.guest_email || '')
                        setEditTicketClass(inv.ticket_class === 'vip' ? 'vip' : 'normal')
                        setEditCustomFields(inv.metadata?.custom_fields || {})
                        setIsEditing(false)
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ fontWeight: 600, color: '#ffffff' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <span>{inv.guest_name_ar || inv.guest_name}</span>
                          {hasAnswers && (
                            <span className="toggle-answers-btn" style={{ color: '#C9A96E', fontSize: '11px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px', marginTop: '4px' }}>
                              عرض وتعديل التفاصيل 🔍
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ color: '#d1d5db' }} dir="ltr">{inv.guest_phone}</td>
                      <td style={{ color: '#d1d5db' }}>{inv.guest_email || <span style={{ color: '#4b5563' }}>—</span>}</td>
                      <td style={{ color: '#9ca3af' }}>{new Date(inv.created_at).toLocaleDateString('ar-SA')}</td>
                      <td>
                        <span style={{
                          padding: '4px 10px',
                          borderRadius: '20px',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          background: inv.rsvp_status === 'accepted' ? 'rgba(16, 185, 129, 0.1)' : (inv.rsvp_status === 'declined' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.1)'),
                          color: inv.rsvp_status === 'accepted' ? '#10b981' : (inv.rsvp_status === 'declined' ? '#ef4444' : '#f59e0b'),
                          border: `1px solid ${inv.rsvp_status === 'accepted' ? 'rgba(16, 185, 129, 0.2)' : (inv.rsvp_status === 'declined' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)')}`
                        }}>
                          {inv.rsvp_status === 'accepted' ? 'مقبول' : (inv.rsvp_status === 'declined' ? 'مرفوض' : 'قيد الانتظار')}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 6 }} onClick={(e) => e.stopPropagation()}>
                          {inv.rsvp_status === 'pending' && (
                            <Can permission={PERM.REG_APPROVE}>
                            <>
                              <button
                                onClick={() => handleApproveApplicant(inv.id)}
                                disabled={updateMutation.isPending}
                                style={{
                                  padding: '6px 12px',
                                  background: '#C9A96E',
                                  color: '#0f172a',
                                  border: 'none',
                                  borderRadius: '6px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  cursor: 'pointer'
                                }}
                              >
                                قبول
                              </button>
                              <button
                                onClick={() => handleDeclineApplicant(inv.id)}
                                disabled={updateMutation.isPending}
                                style={{
                                  padding: '6px 12px',
                                  background: 'rgba(239, 68, 68, 0.1)',
                                  color: '#ef4444',
                                  border: '1px solid rgba(239, 68, 68, 0.2)',
                                  borderRadius: '6px',
                                  fontSize: '0.78rem',
                                  fontWeight: 700,
                                  cursor: 'pointer'
                                }}
                              >
                                رفض
                              </button>
                            </>
                            </Can>
                          )}
                          {inv.rsvp_status !== 'pending' && (
                            <Can permission={PERM.REG_APPROVE}>
                            <button
                              onClick={() => {
                                updateMutation.mutate({
                                  id: inv.id,
                                  data: { status: 'created', rsvp_status: 'pending' }
                                }, {
                                  onSuccess: () => {
                                    refetchInvs()
                                    showAlert('إعادة تعيين بنجاح', 'تمت إعادة تعيين حالة الطلب إلى قيد الانتظار والمراجعة.', 'success')
                                  }
                                })
                              }}
                              disabled={updateMutation.isPending}
                              style={{
                                padding: '6px 12px',
                                background: 'rgba(255, 255, 255, 0.05)',
                                color: '#9ca3af',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: '6px',
                                fontSize: '0.78rem',
                                fontWeight: 600,
                                cursor: 'pointer'
                              }}
                            >
                              إعادة تعيين
                            </button>
                            </Can>
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
      </div>

      {/* ── REGISTRANT DETAILS SIDE-DRAWER ── */}
      {selectedApplicant && (
        <div className="registrant-detail-overlay" onClick={() => setSelectedApplicant(null)}>
          <div className="registrant-detail-panel" onClick={(e) => e.stopPropagation()}>
            <div className="registrant-drawer-header">
              <h3>تفاصيل بيانات المسجل</h3>
              <button className="applicants-modal-close" onClick={() => setSelectedApplicant(null)}>
                <X size={16} />
              </button>
            </div>

            <div className="registrant-drawer-body">
              {/* Profile Summary Card */}
              <div className="registrant-profile-summary">
                <div className="registrant-avatar-circle">
                  {editName ? editName.charAt(0).toUpperCase() : <User size={20} />}
                </div>
                <div className="registrant-summary-meta">
                  <span className="registrant-summary-name">{editName || 'متقدم غير مسمى'}</span>
                  <div>
                    <span style={{
                      padding: '4px 10px',
                      borderRadius: '20px',
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      background: selectedApplicant.rsvp_status === 'accepted' ? 'rgba(16, 185, 129, 0.1)' : (selectedApplicant.rsvp_status === 'declined' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.1)'),
                      color: selectedApplicant.rsvp_status === 'accepted' ? '#10b981' : (selectedApplicant.rsvp_status === 'declined' ? '#ef4444' : '#f59e0b'),
                      border: `1px solid ${selectedApplicant.rsvp_status === 'accepted' ? 'rgba(16, 185, 129, 0.2)' : (selectedApplicant.rsvp_status === 'declined' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.2)')}`
                    }}>
                      {selectedApplicant.rsvp_status === 'accepted' ? 'مقبول' : (selectedApplicant.rsvp_status === 'declined' ? 'مرفوض' : 'قيد الانتظار')}
                    </span>
                  </div>
                </div>
              </div>

              {/* Edit Form / View Details */}
              {!isEditing ? (
                <>
                  {/* View Mode */}
                  <div className="registrant-drawer-section">
                    <h4><User size={13} /> البيانات الأساسية</h4>
                    <div className="registrant-detail-grid">
                      <div className="registrant-detail-item">
                        <User size={14} />
                        <span><strong className="item-label">الاسم الكامل:</strong> {editName}</span>
                      </div>
                      <div className="registrant-detail-item">
                        <Phone size={14} />
                        <span dir="ltr"><strong className="item-label">رقم الجوال:</strong> {editPhone}</span>
                      </div>
                      <div className="registrant-detail-item">
                        <Mail size={14} />
                        <span><strong className="item-label">البريد الإلكتروني:</strong> {editEmail || <span style={{ color: '#64748b' }}>—</span>}</span>
                      </div>
                      <div className="registrant-detail-item">
                        <Calendar size={14} />
                        <span><strong className="item-label">تاريخ التقديم:</strong> {new Date(selectedApplicant.created_at).toLocaleString('ar-SA')}</span>
                      </div>
                      <div className="registrant-detail-item">
                        <Settings size={14} />
                        <span>
                          <strong className="item-label">فئة التذكرة:</strong> 
                          <span className={`registrant-ticket-badge ${editTicketClass}`}>
                            {editTicketClass === 'vip' ? '👑 VIP' : '🎫 عادي'}
                          </span>
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Custom Registration Fields */}
                  {Object.keys(editCustomFields).length > 0 && (
                    <div className="registrant-drawer-section">
                      <h4><ClipboardList size={13} /> الإجابات المخصصة</h4>
                      <div className="registrant-answers-grid">
                        {Object.entries(editCustomFields).map(([question, val]) => (
                          <div key={question} className="registrant-answer-item">
                            <span className="registrant-answer-question">{question}</span>
                            <span className="registrant-answer-value">{Array.isArray(val) ? val.join(', ') : String(val)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Ticket Card Preview / QR code if accepted */}
                  {selectedApplicant.rsvp_status === 'accepted' && (
                    <div className="registrant-drawer-section">
                      <h4><QrCode size={13} /> رمز الدخول والتذكرة</h4>
                      <div className="registrant-detail-qr-section">
                        {selectedApplicant.barcode_png_url ? (
                          <img
                            className="registrant-detail-qr-image"
                            src={selectedApplicant.barcode_png_url}
                            alt="QR Code"
                          />
                        ) : (
                          <LocalQrCode
                            className="registrant-detail-qr-image"
                            value={selectedApplicant.qr_data || `${window.location.origin}/i/${selectedApplicant.token}`}
                            alt="QR Code"
                          />
                        )}
                        <a 
                          href={`${window.location.origin}/i/${selectedApplicant.token}`} 
                          target="_blank" 
                          rel="noopener noreferrer" 
                          style={{ color: '#C9A96E', fontSize: '11px', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px', marginTop: '4px' }}
                        >
                          <ExternalLink size={12} />
                          فتح بطاقة الدعوة الرقمية
                        </a>
                      </div>
                    </div>
                  )}

                  <button className="btn-drawer-edit" onClick={() => setIsEditing(true)}>
                    <Edit3 size={13} />
                    تعديل بيانات المسجل
                  </button>
                </>
              ) : (
                /* Edit Mode */
                <div className="registrant-drawer-section">
                  <h4><Edit3 size={13} /> تعديل البيانات</h4>
                  <div className="registrant-edit-form">
                    <div className="registrant-edit-field">
                      <label>الاسم الكامل</label>
                      <input 
                        type="text" 
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        className="registrant-edit-input"
                      />
                    </div>

                    <div className="registrant-edit-field">
                      <label>رقم الجوال</label>
                      <input 
                        type="text" 
                        value={editPhone}
                        onChange={(e) => setEditPhone(e.target.value)}
                        className="registrant-edit-input ltr-input"
                      />
                    </div>

                    <div className="registrant-edit-field">
                      <label>البريد الإلكتروني</label>
                      <input 
                        type="email" 
                        value={editEmail}
                        onChange={(e) => setEditEmail(e.target.value)}
                        className="registrant-edit-input ltr-input"
                      />
                    </div>

                    <div className="registrant-edit-field">
                      <label>فئة التذكرة الافتراضية</label>
                      <select
                        value={editTicketClass}
                        onChange={(e) => setEditTicketClass(e.target.value as 'vip' | 'normal')}
                        className="registrant-edit-input"
                      >
                        <option value="normal">🎫 عادي (Normal)</option>
                        <option value="vip">👑 VIP</option>
                      </select>
                    </div>

                    {/* Edit Custom Fields */}
                    {Object.keys(editCustomFields).map((question) => (
                      <div key={question} className="registrant-edit-field">
                        <label>{question}</label>
                        <input 
                          type="text" 
                          value={editCustomFields[question] || ''}
                          onChange={(e) => {
                            const newVal = e.target.value
                            setEditCustomFields(prev => ({
                              ...prev,
                              [question]: newVal
                            }))
                          }}
                          className="registrant-edit-input"
                        />
                      </div>
                    ))}

                    <div className="edit-actions-row" style={{ marginTop: '8px' }}>
                      <button className="btn-edit-save" onClick={() => {
                        const updatedData: any = {
                          guest_name_ar: editName,
                          guest_name: editName,
                          guest_phone: editPhone,
                          guest_email: editEmail,
                          ticket_class: editTicketClass,
                          metadata: {
                            ...(selectedApplicant.metadata || {}),
                            custom_fields: editCustomFields
                          }
                        }
                        handleSaveApplicant(selectedApplicant.id, updatedData)
                      }}>
                        <Save size={13} />
                        حفظ التعديلات
                      </button>
                      <button className="btn-edit-cancel" onClick={() => {
                        setIsEditing(false)
                        setEditName(selectedApplicant.guest_name_ar || selectedApplicant.guest_name || '')
                        setEditPhone(selectedApplicant.guest_phone || '')
                        setEditEmail(selectedApplicant.guest_email || '')
                        setEditTicketClass(selectedApplicant.ticket_class === 'vip' ? 'vip' : 'normal')
                        setEditCustomFields(selectedApplicant.metadata?.custom_fields || {})
                      }}>
                        إلغاء
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Drawer Action Bar */}
            {selectedApplicant.rsvp_status === 'pending' && (
              <Can permission={PERM.REG_APPROVE}>
              <div className="registrant-drawer-actions">
                <button 
                  className="btn-drawer-approve"
                  disabled={updateMutation.isPending}
                  onClick={() => {
                    handleApproveApplicant(selectedApplicant.id)
                    setSelectedApplicant(null)
                  }}
                >
                  <CheckCircle size={15} />
                  <span>قبول طلب التسجيل وإصدار الكود</span>
                </button>
                <button 
                  className="btn-drawer-decline"
                  disabled={updateMutation.isPending}
                  onClick={() => {
                    if (handleDeclineApplicant(selectedApplicant.id)) {
                      setSelectedApplicant(null)
                    }
                  }}
                >
                  <XCircle size={15} />
                  <span>رفض طلب الانضمام</span>
                </button>
              </div>
              </Can>
            )}
          </div>
        </div>
      )}

      {/* ── CUSTOM PREMIUM ALERT MODAL ── */}
      {customAlert.show && (
        <div className="custom-alert-overlay" onClick={() => setCustomAlert(prev => ({ ...prev, show: false }))}>
          <div className={`custom-alert-panel ${customAlert.type}`} onClick={(e) => e.stopPropagation()}>
            <div className={`custom-alert-icon-wrapper ${customAlert.type}`}>
              {customAlert.type === 'success' && <CheckCircle size={28} />}
              {customAlert.type === 'error' && <XCircle size={28} />}
              {customAlert.type === 'warning' && <AlertCircle size={28} />}
              {customAlert.type === 'info' && <Sparkles size={28} />}
            </div>
            <h4 className="custom-alert-title">{customAlert.title}</h4>
            <p className="custom-alert-message">{customAlert.message}</p>
            <button 
              className="btn-custom-alert-close"
              onClick={() => setCustomAlert(prev => ({ ...prev, show: false }))}
            >
              موافق
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
