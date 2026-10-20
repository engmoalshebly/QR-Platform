import { motion } from 'framer-motion'
import { TrendingUp } from 'lucide-react'
import type { DashboardTopEvent } from '../types'

const numberFmt = new Intl.NumberFormat('ar')

const statusColors: Record<string, { bg: string; color: string; label: string }> = {
  active:    { bg: 'rgba(34,197,94,0.12)',  color: '#4ade80', label: 'نشط' },
  draft:     { bg: 'rgba(148,163,184,0.12)', color: '#94A3B8', label: 'مسودة' },
  published: { bg: 'rgba(59,130,246,0.12)',  color: '#60a5fa', label: 'منشور' },
  completed: { bg: 'rgba(212,163,44,0.12)', color: '#EAC665', label: 'مكتمل' },
  cancelled: { bg: 'rgba(239,68,68,0.12)',   color: '#f87171', label: 'ملغي' },
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat('ar', { dateStyle: 'medium' }).format(d)
}

interface TopEventsTableProps {
  events: DashboardTopEvent[]
}

const rowVariants = {
  hidden:  { opacity: 0, x: 10 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.3, ease: [0, 0, 0.2, 1] } },
}

export function TopEventsTable({ events }: TopEventsTableProps) {
  if (!events.length) {
    return (
      <div className="events-table-empty">
        <TrendingUp size={20} />
        <span>لا توجد أحداث بعد</span>
      </div>
    )
  }

  return (
    <motion.div
      className="events-table"
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.06 } } }}
    >
      {events.map((event) => {
        const rate = event.total_invitations > 0
          ? Math.round((event.checked_in / event.total_invitations) * 100)
          : 0
        const st = statusColors[event.status] || statusColors.active

        return (
          <motion.div className="events-table__row" key={event.event_id} variants={rowVariants}>
            <div className="events-table__info">
              <strong>{event.event_name}</strong>
              <span>{formatDate(event.event_date)}</span>
            </div>

            {/* mini progress bar */}
            <div className="events-table__progress" title={`${rate}% حضور`}>
              <div className="events-table__track">
                <div
                  className="events-table__fill"
                  style={{ width: `${rate}%` }}
                />
              </div>
              <span className="events-table__rate">{rate}%</span>
            </div>

            <div className="events-table__stats">
              <strong>{numberFmt.format(event.total_invitations)}</strong>
              <span>دعوة</span>
            </div>

            <span className="events-table__chip" style={{ background: st.bg, color: st.color }}>
              {st.label}
            </span>
          </motion.div>
        )
      })}
    </motion.div>
  )
}
