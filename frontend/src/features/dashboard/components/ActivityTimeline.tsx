import { motion } from 'framer-motion'
import { CheckCircle2, Edit3, Trash2, PlusCircle, LogIn, Settings } from 'lucide-react'
import type { DashboardActivity } from '../types'

const ACTION_META: Record<string, { icon: typeof CheckCircle2; color: string; bg: string }> = {
  create:   { icon: PlusCircle,   color: '#4ade80', bg: 'rgba(34,197,94,0.12)' },
  update:   { icon: Edit3,        color: '#60a5fa', bg: 'rgba(59,130,246,0.12)' },
  delete:   { icon: Trash2,       color: '#f87171', bg: 'rgba(239,68,68,0.12)' },
  login:    { icon: LogIn,        color: '#D4A32C', bg: 'rgba(212,163,44,0.12)' },
  settings: { icon: Settings,     color: '#a78bfa', bg: 'rgba(139,92,246,0.12)' },
  default:  { icon: CheckCircle2, color: '#4ade80', bg: 'rgba(34,197,94,0.12)' },
}

function getActionMeta(action: string) {
  const key = action.toLowerCase()
  for (const [k, v] of Object.entries(ACTION_META)) {
    if (key.includes(k)) return v
  }
  return ACTION_META.default
}

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  if (isNaN(then)) return 'غير متوفر'

  const diff = now - then
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'الآن'
  if (minutes < 60) return `منذ ${minutes} دقيقة`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `منذ ${hours} ساعة`
  const days = Math.floor(hours / 24)
  if (days < 7) return `منذ ${days} يوم`
  return new Intl.DateTimeFormat('ar', { dateStyle: 'medium' }).format(new Date(dateStr))
}

interface ActivityTimelineProps {
  items: DashboardActivity[]
  maxItems?: number
}

const listVariants = {
  visible: { transition: { staggerChildren: 0.06 } },
}

const itemVariants = {
  hidden:  { opacity: 0, x: 12 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.35, ease: [0, 0, 0.2, 1] } },
}

export function ActivityTimeline({ items, maxItems = 8 }: ActivityTimelineProps) {
  const visible = items.slice(0, maxItems)

  if (!visible.length) {
    return (
      <div className="timeline-empty">
        <CheckCircle2 size={20} />
        <span>لا يوجد نشاط مسجل بعد</span>
      </div>
    )
  }

  return (
    <motion.div
      className="activity-timeline"
      initial="hidden"
      animate="visible"
      variants={listVariants}
    >
      {visible.map((item, i) => {
        const meta = getActionMeta(item.action)
        const Icon = meta.icon
        return (
          <motion.div className="timeline-item" key={`${item.action}-${i}`} variants={itemVariants}>
            {/* connector line */}
            {i < visible.length - 1 && <span className="timeline-connector" />}

            {/* dot */}
            <span className="timeline-dot" style={{ background: meta.bg, color: meta.color }}>
              <Icon size={14} />
            </span>

            {/* content */}
            <div className="timeline-content">
              <strong>{item.action}</strong>
              <span>{item.resource_type || 'system'}</span>
            </div>

            {/* meta */}
            <div className="timeline-meta">
              <span className="timeline-time">{relativeTime(item.created_at)}</span>
              <span className="timeline-actor">{item.actor_name || 'النظام'}</span>
            </div>
          </motion.div>
        )
      })}
    </motion.div>
  )
}
