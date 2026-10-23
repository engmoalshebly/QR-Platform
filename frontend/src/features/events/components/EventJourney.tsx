import { ArrowLeft, Check } from 'lucide-react'
import type { EventModel, EventStats } from '../types'
import './event-journey.css'

export type JourneyTarget = 'overview' | 'templates' | 'invitations' | 'publish' | 'final_invitations' | 'analytics'

export interface JourneyStep {
  id: JourneyTarget
  title: string
  hint: string
  done: boolean
  /** The step is not available to the current user (permission) */
  locked?: boolean
}

/** Ordered setup path of an event; the first unfinished step is the one to do next. */
export function buildJourney(event: EventModel, stats: EventStats | undefined, templateCount: number): JourneyStep[] {
  const invitations = stats?.total_invitations ?? 0
  const published = event.status !== 'draft'
  return [
    { id: 'overview', title: 'بيانات المناسبة', hint: 'الموقع والتاريخ وحصص الدعوات', done: Boolean(event.venue_name || event.venue_address) },
    { id: 'templates', title: 'تصميم الدعوة', hint: 'اختر تصميماً، أو تجاوز الخطوة واستخدم الدعوة السريعة', done: templateCount > 0 || invitations > 0 },
    { id: 'invitations', title: 'إنشاء الدعوات', hint: 'أضف الضيوف أو استورد قائمتهم من ملف', done: invitations > 0 },
    { id: 'publish', title: 'نشر المناسبة', hint: 'يفعّل الروابط والتسجيل وتأكيد الحضور', done: published },
    { id: 'final_invitations', title: 'إرسال الدعوات', hint: 'أرسل الدعوات الجاهزة للضيوف', done: (stats?.sent_count ?? 0) > 0 },
    { id: 'analytics', title: 'متابعة الحضور', hint: 'تابع الردود والدخول لحظة بلحظة', done: (stats?.checked_in_count ?? 0) > 0 },
  ]
}

export function EventJourney({ steps, onOpen }: { steps: JourneyStep[]; onOpen: (id: JourneyTarget) => void }) {
  const available = steps.filter(step => !step.locked)
  const next = available.find(step => !step.done)
  const doneCount = steps.filter(step => step.done).length
  const percent = Math.round(doneCount / steps.length * 100)

  return (
    <section className="journey" aria-label="خطوات تجهيز المناسبة">
      <div className="journey__head">
        <div>
          <h2>{next ? 'خطوات تجهيز مناسبتك' : 'مناسبتك جاهزة'}</h2>
          <p>{next ? 'اتبع الخطوات بالترتيب؛ كل خطوة تفتح القسم المناسب لها.' : 'اكتملت كل الخطوات. تابع الحضور من الإحصائيات.'}</p>
        </div>
        <div className="journey__progress" aria-label={`اكتمل ${doneCount} من ${steps.length}`}>
          <strong>{doneCount}/{steps.length}</strong>
          <span className="journey__bar"><i style={{ width: `${percent}%` }} /></span>
        </div>
      </div>
      <ol className="journey__steps">
        {steps.map((step, index) => {
          const current = next?.id === step.id
          return (
            <li key={step.id} className={`journey__step${step.done ? ' is-done' : ''}${current ? ' is-current' : ''}`}>
              <button type="button" disabled={step.locked} onClick={() => onOpen(step.id)} aria-current={current ? 'step' : undefined}>
                <span className="journey__marker">{step.done ? <Check size={14} strokeWidth={3} /> : index + 1}</span>
                <span className="journey__text"><strong>{step.title}</strong><small>{step.hint}</small></span>
              </button>
            </li>
          )
        })}
      </ol>
      {next && (
        <div className="journey__next">
          <div><small>الخطوة التالية</small><strong>{next.title}</strong><span>{next.hint}</span></div>
          <button type="button" className="btn btn-primary" onClick={() => onOpen(next.id)}>
            {next.id === 'publish' ? 'نشر المناسبة' : 'ابدأ الآن'}<ArrowLeft size={16} />
          </button>
        </div>
      )}
    </section>
  )
}
