import { useState } from 'react'
import { ArrowLeft, Check, ChevronDown } from 'lucide-react'
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
    { id: 'overview', title: 'بيانات المناسبة', hint: 'الموقع ووقت البداية والنهاية وحصص الدعوات', done: Boolean((event.venue_name || event.venue_address) && event.end_date) },
    { id: 'templates', title: 'تصميم الدعوة', hint: 'اختر تصميماً، أو تجاوز الخطوة واستخدم الدعوة السريعة', done: templateCount > 0 || invitations > 0 },
    { id: 'invitations', title: 'إنشاء الدعوات', hint: 'أضف الضيوف أو استورد قائمتهم من ملف', done: invitations > 0 },
    { id: 'publish', title: 'نشر المناسبة', hint: 'يفعّل الروابط والتسجيل وتأكيد الحضور', done: published },
    { id: 'final_invitations', title: 'إرسال الدعوات', hint: 'أرسل الدعوات الجاهزة للضيوف', done: (stats?.sent_count ?? 0) > 0 },
    { id: 'analytics', title: 'متابعة الحضور', hint: 'تابع الردود والدخول لحظة بلحظة', done: (stats?.checked_in_count ?? 0) > 0 },
  ]
}

const COLLAPSE_KEY = 'qentry_event_journey_collapsed'

export function EventJourney({ steps, onOpen }: { steps: JourneyStep[]; onOpen: (id: JourneyTarget) => void }) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) !== 'false' } catch { return true }
  })
  const toggle = () => setCollapsed(previous => {
    try { localStorage.setItem(COLLAPSE_KEY, String(!previous)) } catch { /* preference only */ }
    return !previous
  })
  const available = steps.filter(step => !step.locked)
  const next = available.find(step => !step.done)
  const doneCount = steps.filter(step => step.done).length
  const percent = Math.round(doneCount / steps.length * 100)

  return (
    <section className="journey" aria-label="خطوات تجهيز المناسبة">
      <div className="journey__head">
        <div className="journey__title">
          <h2>{next ? 'خطوات تجهيز مناسبتك' : 'مناسبتك جاهزة'}</h2>
          <span className="journey__count" aria-label={`اكتمل ${doneCount} من ${steps.length}`}>{doneCount}/{steps.length}</span>
          <span className="journey__bar"><i style={{ width: `${percent}%` }} /></span>
        </div>
        <div className="journey__actions">
          {next && (
            <button type="button" className="btn btn-primary journey__cta" onClick={() => onOpen(next.id)}>
              <span>{next.id === 'publish' ? 'نشر المناسبة' : `التالي: ${next.title}`}</span><ArrowLeft size={14} />
            </button>
          )}
          <button type="button" className="journey__toggle" aria-expanded={!collapsed} onClick={toggle}>
            {collapsed ? 'عرض الخطوات' : 'إخفاء'}<ChevronDown size={14} className={collapsed ? '' : 'is-open'} />
          </button>
        </div>
      </div>
      {!collapsed && <ol className="journey__steps">
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
      </ol>}
    </section>
  )
}
