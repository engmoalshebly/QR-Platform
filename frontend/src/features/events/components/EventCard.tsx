/**
 * EventCard.tsx
 * Standalone presentational card for a single event.
 * Extracted from EventsPage to keep the page file lean.
 */
import { CalendarDays, MapPin, Ticket, Crown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { EventModel } from '../types'
import { getStatusConfig, formatDateFull, calcOccupancy } from '../utils/eventUtils'

interface Props {
  event: EventModel
  /** Optional: pre-fetched checked-in count for progress display */
  checkedIn?: number
}

export function EventCard({ event, checkedIn = 0 }: Props) {
  const navigate = useNavigate()
  const { label, css } = getStatusConfig(event.status)

  const totalQuota = (event.vip_quota ?? 0) + (event.normal_quota ?? 0)
  const occupancyPct = calcOccupancy(checkedIn, totalQuota)

  // Derive theme accent: use theme_color or fall back to golden primary
  const accent = event.theme_color ?? '#D4A32C'

  return (
    <div
      className="event-card"
      style={{ ['--event-accent' as string]: accent }}
      onClick={() => navigate(`/events/${event.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/events/${event.id}`)}
      aria-label={`فتح مناسبة: ${event.title}`}
    >
      {/* ── Banner ── */}
      <div
        className="event-card__banner"
        style={{
          backgroundImage: event.cover_image_url ? `url(${event.cover_image_url})` : undefined,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        {/* Decorative glow blob - only show if no cover image to prevent overlap */}
        {!event.cover_image_url && (
          <div
            className="event-card__glow"
            style={{ background: `radial-gradient(circle at 70% 50%, ${accent}33 0%, transparent 70%)` }}
          />
        )}
        {/* Status badge */}
        <span className={`event-card__status status-badge--${css}`}>{label}</span>
      </div>

      {/* ── Content ── */}
      <div className="event-card__content">
        {/* Icon + Title */}
        <div className="event-card__top">
          <div className="event-card__icon" style={{ borderColor: `${accent}55`, color: accent }}>
            <CalendarDays size={22} />
          </div>
          <h3 className="event-card__title">{event.title}</h3>
        </div>

        {/* Meta */}
        <div className="event-card__meta">
          <div className="event-card__meta-item">
            <CalendarDays size={13} />
            <span>{formatDateFull(event.start_date)}</span>
          </div>
          {event.venue_name && (
            <div className="event-card__meta-item">
              <MapPin size={13} />
              <span>
                {event.venue_name}
                {event.venue_city ? `، ${event.venue_city}` : ''}
              </span>
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="event-card__footer">
          {/* Quotas */}
          <div className="event-card__quotas">
            {event.vip_quota > 0 && (
              <div className="event-card__quota event-card__quota--vip" title="حصة VIP">
                <Crown size={12} />
                <span>{event.vip_quota}</span>
              </div>
            )}
            {event.normal_quota > 0 && (
              <div className="event-card__quota event-card__quota--normal" title="الحصة العادية">
                <Ticket size={12} />
                <span>{event.normal_quota}</span>
              </div>
            )}
          </div>

          {/* RSVP badge */}
          <span className="event-card__badge">
            {event.allow_rsvp ? 'تأكيد الحضور' : 'دعوات مباشرة'}
          </span>
        </div>

        {/* ── Occupancy Progress Bar ── */}
        {totalQuota > 0 && (
          <div className="event-card__progress-wrap">
            <div
              className="event-card__progress-bar"
              style={{
                width: `${occupancyPct}%`,
                background: occupancyPct >= 90
                  ? '#fca5a5'
                  : occupancyPct >= 60
                  ? '#fcd34d'
                  : accent,
              }}
              role="progressbar"
              aria-valuenow={occupancyPct}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        )}
      </div>
    </div>
  )
}
