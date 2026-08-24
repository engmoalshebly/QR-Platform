/**
 * RsvpDetailPanel.tsx
 * Side-drawer panel for viewing guest details, card preview,
 * and performing manual RSVP updates (accept, decline, plus-ones, message).
 */
import { useState, useEffect } from 'react'
import {
  X, User, Phone, Mail, MapPin, Sparkles, Copy,
  ExternalLink, MessageSquare, UserPlus, CheckCircle2,
  XCircle, Clock, Loader2, Save, QrCode
} from 'lucide-react'
import type { Invitation, RsvpStatus } from '@features/invitations/types'
import { LocalQrCode } from '@shared/components/LocalQrCode'

interface Props {
  invitation: Invitation | null
  onClose: () => void
  onUpdateRsvp: (
    id: string,
    status: RsvpStatus,
    plusOneCount?: number,
    message?: string | null,
    guestCount?: number
  ) => Promise<void>
  isUpdating: boolean
  allowRsvp?: boolean
}

export function RsvpDetailPanel({ invitation: inv, onClose, onUpdateRsvp, isUpdating, allowRsvp = true }: Props) {
  const [rsvpStatus, setRsvpStatus] = useState<RsvpStatus>('pending')
  const [plusOne, setPlusOne] = useState(0)
  const [message, setMessage] = useState('')
  const [guestCount, setGuestCount] = useState(1)
  const [copied, setCopied] = useState(false)

  // Sync state with selected invitation
  useEffect(() => {
    if (inv) {
      setRsvpStatus(inv.rsvp_status || 'pending')
      setPlusOne(inv.plus_one_count || 0)
      setMessage(inv.rsvp_message || '')
      setGuestCount(inv.guest_count || 1)
      setCopied(false)
    }
  }, [inv])

  if (!inv) return null

  const isVip = inv.ticket_class === 'vip'
  const publicUrl = `${window.location.origin}/i/${inv.token}`

  const handleCopyLink = () => {
    navigator.clipboard.writeText(publicUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleSave = async () => {
    await onUpdateRsvp(inv.id, rsvpStatus, plusOne, message, guestCount)
  }

  return (
    <div className="inv-detail-overlay" onClick={onClose}>
      <aside className="inv-detail-panel" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="inv-detail-header">
          <h2>تفاصيل رد الضيف (RSVP)</h2>
          <button className="dialog-close" onClick={onClose}><X size={18} /></button>
        </div>

        {/* QR Code / Barcode (Always Prominent) */}
        <div className="inv-detail-qr">
          {inv.barcode_png_url ? (
            <img src={inv.barcode_png_url} alt="QR Code" />
          ) : (
            <LocalQrCode value={inv.qr_data || publicUrl} alt="QR Code" />
          )}
        </div>

        {/* Class Badge and Token link */}
        <div className="inv-detail-status-row">
          <span className={`inv-detail-class ${isVip ? 'inv-detail-class--vip' : ''}`}>
            {isVip && <Sparkles size={12} />}
            {isVip ? 'VIP' : 'عادي'}
          </span>
          <span className="inv-detail-token-txt" dir="ltr">@{inv.token}</span>
        </div>

        {/* Public Card Link */}
        <div className="inv-detail-link-box">
          <span className="inv-detail-link-url">{publicUrl}</span>
          <button 
            className="inv-icon-btn" 
            onClick={handleCopyLink} 
            title={copied ? "تم النسخ!" : "نسخ الرابط"}
            style={{ color: copied ? '#10b981' : 'inherit' }}
          >
            <Copy size={14} />
          </button>
          <a 
            href={publicUrl} 
            target="_blank" 
            rel="noopener noreferrer" 
            className="inv-icon-btn" 
            title="فتح الرابط"
          >
            <ExternalLink size={14} />
          </a>
        </div>

        {/* Card Preview Section (Only shown if available) */}
        {(inv.card_image_url || inv.render_image_url) && (
          <div className="inv-detail-section">
            <h4>معاينة بطاقة الدعوة</h4>
            <div className="rsvp-detail-card-preview" style={{ margin: '8px 0 0 0' }}>
              <img src={inv.card_image_url || inv.render_image_url || ''} alt="بطاقة الدعوة" />
            </div>
          </div>
        )}

        {/* Guest Info Section */}
        <div className="inv-detail-section">
          <h4>بيانات الضيف</h4>
          <div className="inv-detail-grid">
            <div className="inv-detail-item">
              <User size={14} />
              <span>{inv.guest_name_ar || inv.guest_name || 'ضيف غير مسمى'}</span>
            </div>
            {inv.guest_phone && (
              <div className="inv-detail-item">
                <Phone size={14} />
                <span dir="ltr">{inv.guest_phone}</span>
              </div>
            )}
            {inv.guest_email && (
              <div className="inv-detail-item">
                <Mail size={14} />
                <span dir="ltr">{inv.guest_email}</span>
              </div>
            )}
          </div>
        </div>

        {/* Seating Info Section */}
        {(inv.seat_number || inv.table_number || inv.hall || inv.zone) && (
          <div className="inv-detail-section">
            <h4>معلومات الجلوس والدخول</h4>
            <div className="inv-detail-grid">
              {inv.hall && (
                <div className="inv-detail-item"><MapPin size={14} /> <span>القاعة: {inv.hall}</span></div>
              )}
              {inv.table_number && (
                <div className="inv-detail-item"><MapPin size={14} /> <span>طاولة رقم: {inv.table_number}</span></div>
              )}
              {inv.seat_number && (
                <div className="inv-detail-item"><MapPin size={14} /> <span>مقعد رقم: {inv.seat_number}</span></div>
              )}
            </div>
          </div>
        )}

        {/* Barcode Check-In Details Section */}
        <div className="inv-detail-section">
          <h4>تفاصيل قراءة الباركود والدخول</h4>
          <div className="inv-detail-grid">
            <div className="inv-detail-item" style={{ justifyContent: 'space-between', width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckCircle2 size={14} style={{ color: inv.checkin_count > 0 ? '#10b981' : 'var(--color-text-muted)' }} />
                <span>حالة الدخول الفعلي:</span>
              </div>
              <span className={`rsvp-status-badge rsvp-status-badge--${inv.checkin_count > 0 ? 'accepted' : 'pending'}`}>
                {inv.checkin_count > 0 ? 'تم الدخول' : 'لم يحضر بعد'}
              </span>
            </div>
            
            {inv.checked_in_at && (
              <div className="inv-detail-item" style={{ justifyContent: 'space-between', width: '100%' }}>
                <span>توقيت الدخول الأول:</span>
                <span dir="ltr" style={{ fontSize: '0.8rem', opacity: 0.85 }}>
                  {new Date(inv.checked_in_at).toLocaleString('ar-SA')}
                </span>
              </div>
            )}

            <div className="inv-detail-item" style={{ justifyContent: 'space-between', width: '100%' }}>
              <span>مرات القراءة الحالية:</span>
              <strong style={{ color: inv.checkin_count > 0 ? '#10b981' : 'inherit' }}>
                {inv.checkin_count || 0} {inv.checkin_count === 1 ? 'مرة واحدة' : `${inv.checkin_count || 0} مرات`}
              </strong>
            </div>

            <div className="inv-detail-item" style={{ justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
              <span>الحد الأقصى للمسموح:</span>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>
                {inv.guest_count || 1} {inv.guest_count === 1 ? 'مرة واحدة' : `${inv.guest_count || 1} مرات`}
              </span>
            </div>
          </div>
        </div>

        {/* RSVP Management Form Section */}
        <div className="inv-detail-section" style={{ background: 'rgba(255,255,255,0.01)' }}>
          <h4>{allowRsvp ? 'إجراءات تأكيد الحضور (RSVP) وإعدادات الدخول' : 'إعدادات الدخول والباركود'}</h4>
          
          <div className="rsvp-panel-form">
            {/* Status Selection */}
            {allowRsvp && (
              <div className="rsvp-panel-form-group">
                <label>حالة حضور الضيف</label>
                <div className="rsvp-panel-status-toggles">
                  <button
                    type="button"
                    className={`rsvp-panel-status-btn rsvp-panel-status-btn--accepted ${rsvpStatus === 'accepted' ? 'active' : ''}`}
                    onClick={() => setRsvpStatus('accepted')}
                  >
                    <CheckCircle2 size={15} />
                    <span>مقبول</span>
                  </button>
                  <button
                    type="button"
                    className={`rsvp-panel-status-btn rsvp-panel-status-btn--declined ${rsvpStatus === 'declined' ? 'active' : ''}`}
                    onClick={() => setRsvpStatus('declined')}
                  >
                    <XCircle size={15} />
                    <span>معتذر</span>
                  </button>
                  <button
                    type="button"
                    className={`rsvp-panel-status-btn rsvp-panel-status-btn--pending ${rsvpStatus === 'pending' ? 'active' : ''}`}
                    onClick={() => setRsvpStatus('pending')}
                  >
                    <Clock size={15} />
                    <span>بانتظار الرد</span>
                  </button>
                </div>
              </div>
            )}

            {/* Plus One Selector (only shown if accepted) */}
            {allowRsvp && rsvpStatus === 'accepted' && (
              <div className="rsvp-panel-form-group">
                <label className="label-with-icon">
                  <UserPlus size={14} />
                  <span>عدد المرافقين الإضافيين</span>
                </label>
                <div className="rsvp-panel-counter">
                  <button 
                    type="button" 
                    onClick={() => setPlusOne(Math.max(0, plusOne - 1))}
                  >
                    -
                  </button>
                  <span className="rsvp-counter-value">{plusOne}</span>
                  <button 
                    type="button" 
                    onClick={() => setPlusOne(Math.min(10, plusOne + 1))}
                  >
                    +
                  </button>
                </div>
              </div>
            )}

            {/* Allowed Scans / Guest Count Selector */}
            <div className="rsvp-panel-form-group">
              <label className="label-with-icon">
                <QrCode size={14} />
                <span>عدد مرات الدخول المسموح بها للباركود</span>
              </label>
              <div className="rsvp-panel-counter">
                <button 
                  type="button" 
                  onClick={() => setGuestCount(Math.max(1, guestCount - 1))}
                >
                  -
                </button>
                <span className="rsvp-counter-value">{guestCount}</span>
                <button 
                  type="button" 
                  onClick={() => setGuestCount(Math.min(20, guestCount + 1))}
                >
                  +
                </button>
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginTop: '2px', textAlign: 'right', display: 'block' }}>
                * بعد استهلاك هذا العدد من القراءات عند البوابات، لن يُسمح للدعوة بالدخول مرة أخرى.
              </span>
            </div>

            {/* RSVP greeting message */}
            {allowRsvp && (
              <div className="rsvp-panel-form-group">
                <label className="label-with-icon">
                  <MessageSquare size={14} />
                  <span>رسالة الضيف</span>
                </label>
                <textarea
                  placeholder="اكتب رسالة التهنئة أو الاعتذار نيابة عن الضيف..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  maxLength={300}
                  rows={3}
                />
              </div>
            )}

            {/* Action Buttons */}
            <div className="rsvp-panel-submit-container">
              <button
                type="button"
                className="rsvp-panel-submit-btn"
                onClick={handleSave}
                disabled={isUpdating}
              >
                {isUpdating ? (
                  <Loader2 size={16} className="spin" />
                ) : (
                  <Save size={16} />
                )}
                <span>حفظ وإجراء التغييرات</span>
              </button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  )
}
