import { useMemo } from 'react'
import {
  Users,
  CheckCircle2,
  XCircle,
  Eye,
  Crown,
  Ticket,
  Activity,
  TrendingUp,
  Mail,
  CalendarDays,
  MapPin,
  Globe
} from 'lucide-react'
import type { EventStats, EventModel } from '../types'
import { MiniDonutChart } from '@features/dashboard/components/MiniDonutChart'
import { calcOccupancy, getStatusConfig, formatDateFull } from '../utils/eventUtils'
import { motion } from 'framer-motion'

interface Props {
  event: EventModel
  stats: EventStats | undefined
  isLoading?: boolean
}

const numberFmt = new Intl.NumberFormat('ar')

function n(value?: number) {
  return numberFmt.format(value || 0)
}

function pct(part?: number, total?: number) {
  if (!total) return 0
  return Math.min(100, Math.round(((part || 0) / total) * 100))
}

export function EventAnalyticsTab({ event, stats, isLoading }: Props) {
  const { label: statusLabel, css: statusCss } = getStatusConfig(event.status)
  const totalInvitations = stats?.total_invitations ?? 0
  const accepted = stats?.accepted_count ?? 0
  const checkedIn = stats?.checked_in_count ?? 0
  const declined = stats?.declined_count ?? 0
  const pending = Math.max(0, totalInvitations - accepted - declined)

  const rsvpRate = pct(accepted, totalInvitations)
  const attendanceRate = pct(checkedIn, accepted || totalInvitations || 1)
  const deliveryRate = pct(stats?.sent_count ?? 0, totalInvitations)

  const donutSegments = useMemo(() => [
    { value: accepted, color: '#10B981', label: 'مقبول (RSVP)' },
    { value: declined, color: '#EF4444', label: 'اعتذار' },
    { value: pending, color: 'rgba(255,255,255,0.18)', label: 'معلق' },
  ].filter(s => s.value > 0), [accepted, declined, pending])

  const vipPercentage = calcOccupancy(stats?.vip_count ?? 0, event.vip_quota)
  const normalPercentage = calcOccupancy(stats?.normal_count ?? 0, event.normal_quota)

  if (isLoading) {
    return (
      <div className="analytics-skeleton">
        <div className="analytics-skel-grid">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="analytics-skel-card animate-pulse" />
          ))}
        </div>
        <div className="analytics-skel-bento">
          <div className="analytics-skel-card animate-pulse" style={{ height: 320 }} />
          <div className="analytics-skel-card animate-pulse" style={{ height: 320 }} />
        </div>
      </div>
    )
  }

  return (
    <div className="event-analytics-container">
      {/* ── Event Summary Details Hero ── */}
      <motion.div
        className="event-analytics-header"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <div className="analytics-header-left">
          <div className="analytics-status-slug-row">
            <span className={`event-card__status status-badge--${statusCss}`} style={{ position: 'relative', top: 0, right: 0 }}>
              {statusLabel}
            </span>
            {event.slug && (
              <a
                href={`/e/${event.slug}`}
                target="_blank"
                rel="noreferrer"
                className="analytics-slug-link"
              >
                <Globe size={13} />
                /e/{event.slug}
              </a>
            )}
          </div>
          <div className="analytics-meta-row">
            <span>
              <CalendarDays size={14} />
              {formatDateFull(event.start_date)}
            </span>
            {event.venue_name && (
              <span>
                <MapPin size={14} />
                {event.venue_name}
                {event.venue_city ? `، ${event.venue_city}` : ''}
              </span>
            )}
          </div>
        </div>
      </motion.div>

      {/* ── KPI Grid ── */}
      <div className="analytics-kpi-grid">
        <motion.div
          className="analytics-kpi-card tone-gold"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div className="kpi-header">
            <span className="kpi-icon-wrap">
              <Users size={18} />
            </span>
            <span className="kpi-title">إجمالي الدعوات</span>
          </div>
          <div className="kpi-body">
            <h3 className="kpi-value">{n(totalInvitations)}</h3>
            <span className="kpi-desc">
              موزعة على {n(stats?.vip_count)} VIP و {n(stats?.normal_count)} عادي
            </span>
          </div>
        </motion.div>

        <motion.div
          className="analytics-kpi-card tone-green"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.05 }}
        >
          <div className="kpi-header">
            <span className="kpi-icon-wrap">
              <CheckCircle2 size={18} />
            </span>
            <span className="kpi-title">حضور مؤكد</span>
          </div>
          <div className="kpi-body">
            <h3 className="kpi-value">{n(accepted)}</h3>
            <span className="kpi-desc">نسبة تأكيد الحضور: {rsvpRate}%</span>
          </div>
        </motion.div>

        <motion.div
          className="analytics-kpi-card tone-blue"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <div className="kpi-header">
            <span className="kpi-icon-wrap">
              <Eye size={18} />
            </span>
            <span className="kpi-title">تسجيل الدخول</span>
          </div>
          <div className="kpi-body">
            <h3 className="kpi-value">{n(checkedIn)}</h3>
            <span className="kpi-desc">نسبة الحضور الفعلي: {attendanceRate}%</span>
          </div>
        </motion.div>

        <motion.div
          className="analytics-kpi-card tone-red"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.15 }}
        >
          <div className="kpi-header">
            <span className="kpi-icon-wrap">
              <XCircle size={18} />
            </span>
            <span className="kpi-title">الاعتذارات</span>
          </div>
          <div className="kpi-body">
            <h3 className="kpi-value">{n(declined)}</h3>
            <span className="kpi-desc">نسبة الاعتذار: {pct(declined, totalInvitations)}%</span>
          </div>
        </motion.div>
      </div>

      {/* ── Bento Grid: Charts & Quotas ── */}
      <div className="analytics-bento-grid">
        {/* RSVP Status Chart */}
        <motion.div
          className="analytics-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
        >
          <div className="panel-header">
            <div>
              <span className="panel-kicker">حالة الدعوات</span>
              <h3 className="panel-title">تفاصيل الاستجابة للحدث</h3>
            </div>
            <TrendingUp size={18} className="panel-icon" />
          </div>

          <div className="chart-layout">
            <div className="chart-wrapper">
              <MiniDonutChart
                segments={donutSegments}
                size={140}
                strokeWidth={14}
                centerValue={`${rsvpRate}%`}
                centerLabel="تأكيد الحضور"
              />
            </div>
            <div className="chart-legend">
              <div className="legend-item">
                <span className="legend-dot" style={{ background: '#10B981' }} />
                <span className="legend-label">مؤكد: <strong>{n(accepted)}</strong></span>
              </div>
              <div className="legend-item">
                <span className="legend-dot" style={{ background: '#EF4444' }} />
                <span className="legend-label">اعتذر: <strong>{n(declined)}</strong></span>
              </div>
              <div className="legend-item">
                <span className="legend-dot" style={{ background: 'rgba(255,255,255,0.25)' }} />
                <span className="legend-label">معلق: <strong>{n(pending)}</strong></span>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Quota Limits */}
        <motion.div
          className="analytics-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.25 }}
        >
          <div className="panel-header">
            <div>
              <span className="panel-kicker">حدود الكوتة</span>
              <h3 className="panel-title">استهلاك الحصص المخصصة</h3>
            </div>
            <Crown size={18} className="panel-icon" />
          </div>

          <div className="quota-bars-list">
            <div className="quota-bar-row">
              <div className="quota-bar-info">
                <div className="quota-label-group">
                  <Crown size={14} className="gold-text" />
                  <strong>حصص VIP</strong>
                </div>
                <span>{n(stats?.vip_count)} من أصل {n(event.vip_quota)}</span>
              </div>
              <div className="quota-bar-track">
                <motion.div
                  className="quota-bar-fill gold-gradient"
                  initial={{ width: 0 }}
                  animate={{ width: `${vipPercentage}%` }}
                  transition={{ duration: 0.8 }}
                />
              </div>
              <span className="quota-percentage">{vipPercentage}%</span>
            </div>

            <div className="quota-bar-row">
              <div className="quota-bar-info">
                <div className="quota-label-group">
                  <Ticket size={14} className="blue-text" />
                  <strong>الحصص العادية</strong>
                </div>
                <span>{n(stats?.normal_count)} من أصل {n(event.normal_quota)}</span>
              </div>
              <div className="quota-bar-track">
                <motion.div
                  className="quota-bar-fill blue-gradient"
                  initial={{ width: 0 }}
                  animate={{ width: `${normalPercentage}%` }}
                  transition={{ duration: 0.8 }}
                />
              </div>
              <span className="quota-percentage">{normalPercentage}%</span>
            </div>
          </div>
        </motion.div>
      </div>

      {/* ── Interaction Funnel ── */}
      <motion.div
        className="analytics-panel full-width-panel"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.3 }}
      >
        <div className="panel-header">
          <div>
            <span className="panel-kicker">مسار التفاعل</span>
            <h3 className="panel-title">تحليلات تسليم وقراءة الدعوات</h3>
          </div>
          <Activity size={18} className="panel-icon" />
        </div>

        <div className="funnel-steps">
          <div className="funnel-step">
            <div className="funnel-step-icon">
              <Mail size={16} />
            </div>
            <div className="funnel-step-meta">
              <h4>تم الإرسال</h4>
              <p>الدعوات التي تم توليدها وإرسالها</p>
            </div>
            <div className="funnel-step-progress">
              <div className="funnel-progress-track">
                <div className="funnel-progress-fill" style={{ width: `${deliveryRate}%`, background: '#60a5fa' }} />
              </div>
              <span className="funnel-rate-value">{n(stats?.sent_count)} دعوة ({deliveryRate}%)</span>
            </div>
          </div>

          <div className="funnel-step">
            <div className="funnel-step-icon">
              <Eye size={16} />
            </div>
            <div className="funnel-step-meta">
              <h4>تم المشاهدة</h4>
              <p>الضيوف الذين فتحوا وقرأوا الدعوة</p>
            </div>
            <div className="funnel-step-progress">
              <div className="funnel-progress-track">
                <div className="funnel-progress-fill" style={{ width: `${pct(stats?.viewed_count, stats?.sent_count || 1)}%`, background: '#D4A32C' }} />
              </div>
              <span className="funnel-rate-value">
                {n(stats?.viewed_count)} مشاهدة ({pct(stats?.viewed_count, stats?.sent_count || 1)}%)
              </span>
            </div>
          </div>

          <div className="funnel-step">
            <div className="funnel-step-icon">
              <CheckCircle2 size={16} />
            </div>
            <div className="funnel-step-meta">
              <h4>الحضور الفعلي</h4>
              <p>الضيوف الذين أكدوا وتم تسجيل دخولهم بالرمز</p>
            </div>
            <div className="funnel-step-progress">
              <div className="funnel-progress-track">
                <div className="funnel-progress-fill" style={{ width: `${pct(checkedIn, totalInvitations || 1)}%`, background: '#10B981' }} />
              </div>
              <span className="funnel-rate-value">
                {n(checkedIn)} حاضر ({pct(checkedIn, totalInvitations || 1)}%)
              </span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
