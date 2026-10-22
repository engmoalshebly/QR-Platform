/**
 * EventSkeletonCard.tsx
 * Shimmer loading placeholder shown while events are being fetched.
 */

export function EventSkeletonCard() {
  return (
    <div className="event-skeleton" aria-hidden="true">
      <div className="event-skeleton__banner shimmer" />
      <div className="event-skeleton__body">
        <div className="event-skeleton__icon shimmer" />
        <div className="event-skeleton__line event-skeleton__line--title shimmer" />
        <div className="event-skeleton__line shimmer" />
        <div className="event-skeleton__line event-skeleton__line--short shimmer" />
        <div className="event-skeleton__footer">
          <div className="event-skeleton__pill shimmer" />
          <div className="event-skeleton__pill event-skeleton__pill--sm shimmer" />
        </div>
      </div>
    </div>
  )
}

/** Renders N skeleton cards */
export function EventSkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="events-grid" role="status" aria-label="جاري تحميل المناسبات">
      {Array.from({ length: count }, (_, i) => (
        <EventSkeletonCard key={i} />
      ))}
    </div>
  )
}
