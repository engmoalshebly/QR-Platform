/**
 * PublicInvitationPage.tsx
 * Public page shown to guests at /i/:token — no auth required.
 * Displays invitation details, event info, QR code, and RSVP buttons.
 */
import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  CalendarDays, MapPin, Clock, CheckCircle2, XCircle,
  Sparkles, Loader2, ExternalLink, Download, Calendar,
  MessageSquare, UserPlus, Info
} from 'lucide-react'
import { LocalQrCode } from '@shared/components/LocalQrCode'
import { invitationsAPI } from '../api/invitationsApi'
import './invitations.css'

// ── Confetti Canvas Component ──
function ConfettiCanvas({ active }: { active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  
  useEffect(() => {
    if (!active) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    
    let animationFrameId: number
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
    
    const colors = ['#C9A96E', '#b08b47', '#86efac', '#60a5fa', '#ffffff', '#fbbf24']
    const particles = Array.from({ length: 120 }).map(() => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height - canvas.height,
      r: Math.random() * 6 + 4,
      d: Math.random() * canvas.height,
      color: colors[Math.floor(Math.random() * colors.length)],
      tilt: Math.random() * 10 - 5,
      tiltAngleIncremental: Math.random() * 0.07 + 0.02,
      tiltAngle: 0
    }))
    
    function draw() {
      if (!ctx || !canvas) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      particles.forEach((p) => {
        p.tiltAngle += p.tiltAngleIncremental
        p.y += (Math.cos(p.d) + 3 + p.r / 2) / 2
        p.x += Math.sin(p.tiltAngle)
        p.tilt = Math.sin(p.tiltAngle - p.r / 2) * 5
        
        ctx.beginPath()
        ctx.lineWidth = p.r
        ctx.strokeStyle = p.color
        ctx.moveTo(p.x + p.tilt + p.r / 2, p.y)
        ctx.lineTo(p.x + p.tilt, p.y + p.tilt + p.r / 2)
        ctx.stroke()
      })
      
      update()
      animationFrameId = requestAnimationFrame(draw)
    }
    
    function update() {
      if (!canvas) return
      particles.forEach((p) => {
        if (p.y > canvas.height) {
          p.x = Math.random() * canvas.width
          p.y = -20
        }
      })
    }
    
    draw()
    
    const handleResize = () => {
      if (!canvas) return
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
    }
    window.addEventListener('resize', handleResize)
    
    return () => {
      cancelAnimationFrame(animationFrameId)
      window.removeEventListener('resize', handleResize)
    }
  }, [active])
  
  if (!active) return null
  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 9999
      }}
    />
  )
}

interface PublicInvitation {
  id: string
  token: string
  status: string
  ticket_class: string
  guest_name: string | null
  guest_name_ar: string | null
  seat_number: string | null
  table_number: string | null
  hall: string | null
  zone: string | null
  barcode_png_url: string | null
  render_image_url: string | null
  card_image_url: string | null
  qr_data: string | null
  rsvp_status: string | null
  rsvp_at?: string | null
  plus_one_count: number
  rsvp_message?: string | null
  event_title: string | null
  event_title_ar: string | null
  start_date: string | null
  end_date: string | null
  venue_name: string | null
  venue_name_ar: string | null
  venue_address: string | null
  venue_map_url: string | null
  allow_rsvp: boolean
  allow_plus_one: boolean
  cover_image_url: string | null
  metadata: Record<string, any> | null
}

export default function PublicInvitationPage() {
  const { token } = useParams<{ token: string }>()
  const [invitation, setInvitation] = useState<PublicInvitation | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rsvpDone, setRsvpDone] = useState(false)
  const [rsvpPending, setRsvpPending] = useState(false)
  const [plusOne, setPlusOne] = useState(0)
  const [message, setMessage] = useState('')
  const [showConfetti, setShowConfetti] = useState(false)
  const [isCalendarDropdownOpen, setIsCalendarDropdownOpen] = useState(false)
  const [downloadingCard, setDownloadingCard] = useState(false)

  useEffect(() => {
    if (!token) return
    setLoading(true)
    invitationsAPI.viewPublic(token)
      .then((data) => {
        setInvitation(data)
        if (data.rsvp_status === 'accepted') {
          setShowConfetti(true)
        }
        if (data.plus_one_count !== undefined) {
          setPlusOne(data.plus_one_count || 0)
        }
        if (data.rsvp_message) {
          setMessage(data.rsvp_message)
        }
      })
      .catch((err) => {
        if (err.response?.status === 410) setError('تم إلغاء هذه الدعوة')
        else if (err.response?.status === 404) setError('الدعوة غير موجودة')
        else setError('حدث خطأ أثناء تحميل الدعوة')
      })
      .finally(() => setLoading(false))
  }, [token])

  const handleRsvp = async (status: 'accepted' | 'declined') => {
    if (!token) return
    setRsvpPending(true)
    try {
      await invitationsAPI.rsvp(token, { status, plus_one_count: plusOne, message })
      setRsvpDone(true)
      setInvitation((prev: PublicInvitation | null) => 
        prev ? { ...prev, rsvp_status: status, plus_one_count: plusOne, rsvp_message: message } : prev
      )
      if (status === 'accepted') {
        setShowConfetti(true)
        // Stop confetti after 7 seconds
        setTimeout(() => setShowConfetti(false), 7000)
      }
    } catch {
      // Ignore errors for now
    }
    setRsvpPending(false)
  }

  const handleDownloadCard = async () => {
    if (!invitation) return
    const imageUrl = invitation.card_image_url || invitation.render_image_url
    if (!imageUrl) return
    
    setDownloadingCard(true)
    try {
      const response = await fetch(imageUrl)
      const blob = await response.blob()
      const blobUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = blobUrl
      link.download = `دعوة_${invitation.guest_name_ar || invitation.guest_name || 'حفل'}.png`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(blobUrl)
    } catch {
      window.open(imageUrl, '_blank')
    } finally {
      setDownloadingCard(false)
    }
  }

  // ── Format Date for iCal ──
  const formatDateToIcal = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
  }

  // ── Calendar URLs ──
  const calendarLinks = useMemo(() => {
    if (!invitation || !invitation.start_date) return null
    const title = invitation.event_title_ar || invitation.event_title || 'مناسبة خاصة'
    const start = formatDateToIcal(invitation.start_date)
    const end = invitation.end_date 
      ? formatDateToIcal(invitation.end_date)
      : formatDateToIcal(new Date(new Date(invitation.start_date).getTime() + 4 * 60 * 60 * 1000).toISOString()) // default +4 hours
    
    const details = `تأكيد الحضور ورابط الدعوة: ${window.location.origin}/i/${invitation.token}`
    const location = `${invitation.venue_name_ar || invitation.venue_name || ''} - ${invitation.venue_address || ''}`

    // Google Calendar
    const google = `https://www.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(title)}&dates=${start}/${end}&details=${encodeURIComponent(details)}&location=${encodeURIComponent(location)}`
    
    // iCal / Outlook (Data URI)
    const icalData = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      'BEGIN:VEVENT',
      `DTSTART:${start}`,
      `DTEND:${end}`,
      `SUMMARY:${title}`,
      `DESCRIPTION:${details}`,
      `LOCATION:${location}`,
      'END:VEVENT',
      'END:VCALENDAR'
    ].join('\n')
    const ical = `data:text/calendar;charset=utf-8,${encodeURIComponent(icalData)}`

    return { google, ical }
  }, [invitation])

  if (loading) {
    return (
      <div className="pub-page pub-page--loading">
        <Loader2 size={40} className="animate-spin" style={{ color: '#C9A96E' }} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="pub-page">
        <div className="pub-error">
          <XCircle size={48} style={{ color: '#ef4444' }} />
          <h2>{error}</h2>
        </div>
      </div>
    )
  }

  if (!invitation) return null

  const inv = invitation
  const isVip = inv.ticket_class === 'vip'

  const needsRsvp = !!(inv.allow_rsvp || inv.metadata?.require_rsvp)
  const hasAccepted = inv.rsvp_status === 'accepted'
  const hasDeclined = inv.rsvp_status === 'declined'

  const customFields = Object.entries(inv.metadata || {}).filter(([key, value]) => {
    const systemKeys = [
      'generation_deleted', 'generation_deleted_at', 'generation_deleted_by', 
      'generation_delete_operation_id', 'imported_from', 'custom_fields', 
      'template_name', 'source', 'template_id', 'ticket_class'
    ]
    return !systemKeys.includes(key) && 
           value !== null && 
           value !== undefined && 
           value !== '' &&
           (typeof value === 'string' || typeof value === 'number')
  })

  return (
    <div className="pub-page">
      <ConfettiCanvas active={showConfetti} />

      <div className="pub-card">
        {/* Cover or Rendered Card */}
        {(!needsRsvp || hasAccepted) && (inv.card_image_url || inv.render_image_url) ? (
          <div className="pub-card__cover">
            <img src={inv.card_image_url || inv.render_image_url!} alt="دعوة" />
            <button 
              className="pub-cover-download" 
              onClick={handleDownloadCard}
              disabled={downloadingCard}
              title="تحميل كرت الدعوة كصورة"
            >
              {downloadingCard ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Download size={16} />
              )}
              <span>حفظ كرت الدعوة</span>
            </button>
          </div>
        ) : inv.cover_image_url ? (
          <div className="pub-card__cover">
            <img src={inv.cover_image_url} alt="غلاف الحدث" />
          </div>
        ) : null}

        {/* Header */}
        <div className="pub-card__header">
          {isVip && (
            <span className="pub-vip-badge"><Sparkles size={14} /> VIP</span>
          )}
          <h1>{inv.event_title_ar || inv.event_title}</h1>
          {inv.guest_name_ar || inv.guest_name ? (
            <p className="pub-guest-name">{inv.guest_name_ar || inv.guest_name}</p>
          ) : null}
        </div>

        {/* Event Details */}
        <div className="pub-details">
          {inv.start_date && (
            <div className="pub-detail-item">
              <CalendarDays size={18} />
              <div>
                <span className="pub-detail-label">التاريخ</span>
                <span className="pub-detail-value">
                  {new Date(inv.start_date).toLocaleDateString('ar', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
                </span>
              </div>
            </div>
          )}
          {inv.start_date && (
            <div className="pub-detail-item">
              <Clock size={18} />
              <div>
                <span className="pub-detail-label">الوقت</span>
                <span className="pub-detail-value">
                  {new Date(inv.start_date).toLocaleTimeString('ar', { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </div>
          )}
          {(inv.venue_name_ar || inv.venue_name) && (
            <div className="pub-detail-item">
              <MapPin size={18} />
              <div>
                <span className="pub-detail-label">المكان</span>
                <span className="pub-detail-value">{inv.venue_name_ar || inv.venue_name}</span>
                {inv.venue_address && <span className="pub-detail-sub">{inv.venue_address}</span>}
              </div>
            </div>
          )}
        </div>

        {/* Seating and Custom info */}
        {(!needsRsvp || hasAccepted) && (inv.seat_number || inv.table_number || inv.hall || customFields.length > 0) && (
          <div className="pub-seating-container">
            <div className="pub-seating-title">
              <Info size={14} />
              <span>تفاصيل الدخول والمقعد</span>
            </div>
            
            {(inv.hall || inv.table_number || inv.seat_number) && (
              <div className="pub-seating-grid">
                {inv.hall && (
                  <div className="pub-seating-card">
                    <span className="pub-seating-card__label">القاعة</span>
                    <strong className="pub-seating-card__value">{inv.hall}</strong>
                  </div>
                )}
                {inv.table_number && (
                  <div className="pub-seating-card">
                    <span className="pub-seating-card__label">الطاولة</span>
                    <strong className="pub-seating-card__value">{inv.table_number}</strong>
                  </div>
                )}
                {inv.seat_number && (
                  <div className="pub-seating-card">
                    <span className="pub-seating-card__label">المقعد</span>
                    <strong className="pub-seating-card__value">{inv.seat_number}</strong>
                  </div>
                )}
              </div>
            )}
            
            {customFields.length > 0 && (
              <div className="pub-custom-fields">
                {customFields.map(([key, value]) => (
                  <div key={key} className="pub-custom-field-row">
                    <span className="pub-custom-field-label">{key}</span>
                    <strong className="pub-custom-field-value">{String(value)}</strong>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* RSVP Notice Box (if RSVP is required and pending) */}
        {needsRsvp && !hasAccepted && !hasDeclined && (
          <div className="pub-rsvp-notice">
            <Info size={16} style={{ flexShrink: 0 }} />
            <span>يرجى تأكيد حضورك أدناه لتوليد كرت الدخول والباركود الخاص بك.</span>
          </div>
        )}

        {/* QR Code */}
        {(!needsRsvp || hasAccepted) && (inv.barcode_png_url || inv.qr_data || inv.token) && (
          <div className="pub-qr">
            {inv.barcode_png_url ? (
              <img src={inv.barcode_png_url} alt="QR Code" />
            ) : (
              <LocalQrCode
                value={inv.qr_data || `${window.location.origin}/i/${inv.token}`}
                alt="QR Code"
              />
            )}
            <span>أظهر هذا الرمز عند الدخول</span>
          </div>
        )}

        {/* Actions Button Panel */}
        <div className="pub-action-buttons">
          {/* Map Link */}
          {inv.venue_map_url && (
            <a href={inv.venue_map_url} target="_blank" rel="noopener noreferrer" className="pub-action-btn pub-action-btn--map">
              <MapPin size={16} /> 
              <span>عرض الموقع الجغرافي</span>
              <ExternalLink size={13} />
            </a>
          )}

          {/* Add to Calendar */}
          {calendarLinks && (
            <div className="pub-calendar-dropdown">
              <button 
                className="pub-action-btn pub-action-btn--calendar" 
                onClick={() => setIsCalendarDropdownOpen(!isCalendarDropdownOpen)}
              >
                <Calendar size={16} />
                <span>حفظ الموعد في التقويم</span>
              </button>
              {isCalendarDropdownOpen && (
                <div className="pub-calendar-menu">
                  <a 
                    href={calendarLinks.google} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    onClick={() => setIsCalendarDropdownOpen(false)}
                  >
                    تقويم Google
                  </a>
                  <a 
                    href={calendarLinks.ical} 
                    download="event.ics"
                    onClick={() => setIsCalendarDropdownOpen(false)}
                  >
                    تقويم Apple / Outlook (iCal)
                  </a>
                </div>
              )}
            </div>
          )}
        </div>

        {/* RSVP Form */}
        {(inv.allow_rsvp || inv.metadata?.require_rsvp) && !rsvpDone && inv.rsvp_status !== 'accepted' && inv.rsvp_status !== 'declined' && (
          <div className="pub-rsvp">
            <h3>هل ستحضر؟</h3>
            
            {/* Plus One selection */}
            {inv.allow_plus_one && (
              <div className="pub-rsvp-interactive-row">
                <div className="pub-rsvp-row-info">
                  <UserPlus size={16} />
                  <span>هل ترغب في إضافة مرافقين؟</span>
                </div>
                <div className="pub-rsvp-counter">
                  <button 
                    type="button" 
                    onClick={() => setPlusOne(Math.max(0, plusOne - 1))}
                  >
                    -
                  </button>
                  <span>{plusOne}</span>
                  <button 
                    type="button" 
                    onClick={() => setPlusOne(Math.min(10, plusOne + 1))}
                  >
                    +
                  </button>
                </div>
              </div>
            )}

            {/* RSVP message greetings */}
            <div className="pub-rsvp-interactive-message">
              <label>
                <MessageSquare size={16} />
                <span>رسالة تهنئة أو اعتذار (اختياري)</span>
              </label>
              <textarea
                placeholder="اكتب رسالتك هنا للمضيف..."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                maxLength={300}
                rows={3}
              />
            </div>

            <div className="pub-rsvp-actions">
              <button
                className="pub-rsvp-btn pub-rsvp-btn--accept"
                onClick={() => handleRsvp('accepted')}
                disabled={rsvpPending}
              >
                <CheckCircle2 size={18} /> نعم، سأحضر
              </button>
              <button
                className="pub-rsvp-btn pub-rsvp-btn--decline"
                onClick={() => handleRsvp('declined')}
                disabled={rsvpPending}
              >
                <XCircle size={18} /> لا، أعتذر
              </button>
            </div>
          </div>
        )}

        {/* RSVP Done */}
        {(rsvpDone || inv.rsvp_status === 'accepted' || inv.rsvp_status === 'declined') && (
          <div className={`pub-rsvp-result ${inv.rsvp_status === 'accepted' ? 'pub-rsvp-result--accepted' : 'pub-rsvp-result--declined'}`}>
            {inv.rsvp_status === 'accepted' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center', textAlign: 'center', width: '100%' }}>
                <CheckCircle2 size={24} />
                <strong>تم تأكيد حضورك — نتشرف بلقائك!</strong>
                {inv.plus_one_count > 0 && (
                  <span style={{ fontSize: '12px', opacity: 0.8 }}>معك {inv.plus_one_count} مرافقين</span>
                )}
                {inv.rsvp_message && (
                  <div className="pub-rsvp-saved-message">
                    <span className="pub-rsvp-message-quote">«</span>
                    <span>{inv.rsvp_message}</span>
                    <span className="pub-rsvp-message-quote">»</span>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center', textAlign: 'center', width: '100%' }}>
                <XCircle size={24} />
                <strong>شكراً لتبليغنا — نتمنى لقاءك في مناسبة أخرى</strong>
                {inv.rsvp_message && (
                  <div className="pub-rsvp-saved-message">
                    <span className="pub-rsvp-message-quote">«</span>
                    <span>{inv.rsvp_message}</span>
                    <span className="pub-rsvp-message-quote">»</span>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="pub-footer">
          <span>مدعوم بواسطة Qentry</span>
        </div>
      </div>
    </div>
  )
}
