/**
 * EventStatsStrip.tsx
 * Visual stats bar displayed at the top of the event detail page.
 * Shows live invitation counts with visual progress bars.
 */
import { Users, CheckCircle2, Eye, Crown, Ticket, XCircle } from 'lucide-react'
import type { EventStats, EventModel } from '../types'
import { calcOccupancy } from '../utils/eventUtils'

interface Props {
  event: EventModel
  stats: EventStats | undefined
  isLoading?: boolean
}

interface StatBoxProps {
  label: string
  value: number | string
  icon: React.ReactNode
  accent?: string
  subBar?: { value: number; max: number; color?: string }
  isLoading?: boolean
}

function StatBox({ label, value, icon, accent, subBar, isLoading }: StatBoxProps) {
  const pct = subBar ? calcOccupancy(subBar.value, subBar.max) : 0

  return (
    <div className="event-stat-box" style={accent ? { borderColor: `${accent}33` } : {}}>
      <div className="event-stat-box__label">
        <span className="event-stat-box__icon" style={accent ? { color: accent } : {}}>
          {icon}
        </span>
        <span>{label}</span>
      </div>
      {isLoading ? (
        <div className="event-stat-box__value shimmer" style={{ height: 28, borderRadius: 6 }} />
      ) : (
        <strong className="event-stat-box__value" style={accent ? { color: accent } : {}}>
          {value}
        </strong>
      )}
      {subBar && subBar.max > 0 && !isLoading && (
        <div className="event-stat-box__bar-wrap">
          <div
            className="event-stat-box__bar"
            style={{
              width: `${pct}%`,
              background: subBar.color ?? '#D4A32C',
            }}
          />
        </div>
      )}
    </div>
  )
}

export function EventStatsStrip({ event, stats, isLoading }: Props) {
  const totalVipUsed = stats?.vip_count ?? 0
  const totalNormalUsed = stats?.normal_count ?? 0

  return (
    <div className="event-stats-strip">
      <StatBox
        label="إجمالي الدعوات"
        value={stats?.total_invitations ?? 0}
        icon={<Users size={12} />}
        accent="#D4A32C"
        isLoading={isLoading}
      />
      <StatBox
        label="حضور مؤكد (RSVP)"
        value={stats?.accepted_count ?? 0}
        icon={<CheckCircle2 size={12} />}
        accent="#86efac"
        isLoading={isLoading}
      />
      <StatBox
        label="تم تسجيل الدخول"
        value={stats?.checked_in_count ?? 0}
        icon={<Eye size={12} />}
        accent="#60a5fa"
        isLoading={isLoading}
      />
      <StatBox
        label="رُفضت"
        value={stats?.declined_count ?? 0}
        icon={<XCircle size={12} />}
        isLoading={isLoading}
      />
      <StatBox
        label="حصة VIP"
        value={`${totalVipUsed} / ${event.vip_quota}`}
        icon={<Crown size={12} />}
        accent="#D4A32C"
        subBar={{ value: totalVipUsed, max: event.vip_quota, color: '#D4A32C' }}
        isLoading={isLoading}
      />
      <StatBox
        label="الحصة العادية"
        value={`${totalNormalUsed} / ${event.normal_quota}`}
        icon={<Ticket size={12} />}
        subBar={{ value: totalNormalUsed, max: event.normal_quota, color: '#60a5fa' }}
        isLoading={isLoading}
      />
    </div>
  )
}
