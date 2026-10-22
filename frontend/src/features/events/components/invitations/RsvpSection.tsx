import React from 'react'
import { CalendarCheck, Info } from 'lucide-react'

interface RsvpSectionProps {
  requireRsvp: boolean
  setRequireRsvp: (val: boolean) => void
  isMissingContact: boolean
  missingContactCount: number
  missingContactSourceLabel: string
  style?: React.CSSProperties
}

export function RsvpSection({ requireRsvp, setRequireRsvp, isMissingContact, missingContactCount, missingContactSourceLabel, style }: RsvpSectionProps) {
  return (
    <section className="inv-rsvp-card" style={style}>
      <button type="button" className={`inv-rsvp-control ${requireRsvp ? 'inv-rsvp-control--on' : ''}`}
        role="switch" aria-checked={requireRsvp} aria-label="اشتراط تأكيد الضيف قبل الدخول"
        onClick={() => setRequireRsvp(!requireRsvp)}>
        <span className="inv-rsvp-icon"><CalendarCheck size={20} /></span>
        <span className="inv-rsvp-copy">
          <strong>تأكيد الحضور قبل الدخول <small>اختياري</small></strong>
          <span>{requireRsvp ? 'يظهر رمز الدخول للضيف بعد موافقته على الحضور.' : 'الدعوة جاهزة للدخول دون انتظار رد الضيف.'}</span>
        </span>
        <span className={`toggle-switch ${requireRsvp ? 'toggle-switch--on' : ''}`} aria-hidden="true"><span className="toggle-switch__thumb" /></span>
      </button>
      {requireRsvp && (
        <div className="inv-rsvp-guide">
          <ol className="inv-rsvp-steps">
            <li><span>1</span><div><strong>أنشئ الدعوات</strong><small>اسم وجوال أو بريد لكل ضيف</small></div></li>
            <li><span>2</span><div><strong>شارك رابط الضيف</strong><small>من تبويب «ردود الضيوف»</small></div></li>
            <li><span>3</span><div><strong>تابع الردود</strong><small>المؤكدون في «الدعوات الجاهزة للدخول»</small></div></li>
          </ol>
          <details className="inv-rsvp-help">
            <summary><Info size={14} /><span>تفاصيل آلية تأكيد الحضور</span></summary>
            <p>إنشاء الدعوات لا يرسلها تلقائياً؛ انسخ رابط كل ضيف وأرسله إليه. الموافقة تسمح بالدخول، والاعتذار يمنعه. تنزيل PDF لا يطلب الرد، والمسح عند البوابة يسجل الحضور الفعلي.</p>
          </details>
        </div>
      )}
      {isMissingContact && (
        <p className="inv-rsvp-notice" role="status"><Info size={16} /> استخدم إدخال الأسماء أو Excel مع جوال أو بريد لكل ضيف. الإنشاء بالعدد لا يدعم تأكيد الحضور ({missingContactCount} دعوة، {missingContactSourceLabel}).</p>
      )}
    </section>
  )
}
