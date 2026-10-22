/**
 * EventsPage.tsx
 * Clean orchestrator — data fetching delegated to useEventsList hook,
 * UI state delegated to useEventsStore, rendering delegated to components.
 */
import { useState } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import { Plus, CalendarDays, Search, Filter, RefreshCw, LayoutGrid, List } from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { useAuthStore } from '@features/auth/store/authStore'
import { useEventsList } from '../hooks/useEvents'
import { useEventsStore } from '../store/eventsStore'
import { EventCard } from '../components/EventCard'
import { EventSkeletonGrid } from '../components/EventSkeletonCard'
import { CreateEventDialog } from '../components/CreateEventDialog'
import { Can, PERM, usePermission } from '@shared/permissions'
import { getStatusConfig, formatDateShort } from '../utils/eventUtils'
import type { EventStatus } from '../types'
import '@features/users/pages/users.css'
import './events.css'

const STATUS_OPTIONS: { value: EventStatus | ''; label: string }[] = [
  { value: '', label: 'جميع الحالات' },
  { value: 'draft', label: 'مسودة' },
  { value: 'published', label: 'منشور' },
  { value: 'active', label: 'نشط' },
  { value: 'completed', label: 'مكتمل' },
  { value: 'cancelled', label: 'ملغي' },
]

export default function EventsPage() {
  const navigate = useNavigate()
  const currentTenantId = useAuthStore((s) => s.currentTenantId)

  // Guard
  const hasAccess = usePermission(PERM.NAV_EVENTS)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => {
    return (localStorage.getItem('qr-events-view-mode') as 'grid' | 'list') || 'grid'
  })

  const handleViewModeChange = (mode: 'grid' | 'list') => {
    setViewMode(mode)
    localStorage.setItem('qr-events-view-mode', mode)
  }

  // UI state from Zustand
  const { searchQuery, statusFilter, setSearchQuery, setStatusFilter } = useEventsStore()

  // Server state from React Query
  const { data: events, isLoading, isError, refetch } = useEventsList(
    currentTenantId,
    statusFilter,
    hasAccess,
  )

  if (!hasAccess) {
    return <Navigate to="/dashboard" replace />
  }

  if (!currentTenantId) {
    return (
      <WorkspaceShell title="المناسبات" subtitle="">
        <div className="dash-state">
          <CalendarDays size={40} />
          <h1>لا توجد مساحة عمل محددة</h1>
          <p>اختر مساحة العمل لعرض قائمة المناسبات.</p>
        </div>
      </WorkspaceShell>
    )
  }

  // Client-side search filter (status filtering is server-side via query param)
  const filtered = events?.filter((e) => {
    if (!searchQuery.trim()) return true
    const q = searchQuery.toLowerCase()
    return (
      e.title.toLowerCase().includes(q) ||
      (e.venue_name?.toLowerCase().includes(q) ?? false) ||
      (e.venue_city?.toLowerCase().includes(q) ?? false)
    )
  })

  return (
    <WorkspaceShell
      title="المناسبات"
      subtitle="إدارة كافة الفعاليات والمناسبات الخاصة بمساحة العمل"
      actions={
        <Can permission={PERM.EVENT_CREATE}>
          <button className="btn btn-primary" onClick={() => setShowCreateDialog(true)}>
            <Plus size={18} />
            مناسبة جديدة
          </button>
        </Can>
      }
    >
      {/* ── Toolbar ── */}
      <div className="users-toolbar">
        <div className="toolbar-search">
          <Search size={17} className="search-icon" />
          <input
            id="events-search"
            type="text"
            className="users-search"
            placeholder="بحث بالاسم أو المدينة…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="بحث في المناسبات"
          />
        </div>

        <div className="toolbar-filters">
          <div style={{ position: 'relative' }}>
            <Filter
              size={15}
              style={{
                position: 'absolute',
                right: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--color-text-muted)',
                pointerEvents: 'none',
              }}
            />
            <select
              id="events-status-filter"
              className="filter-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as EventStatus | '')}
              style={{ paddingRight: '36px' }}
              aria-label="فلترة حسب الحالة"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="view-toggles">
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === 'grid' ? 'view-toggle-btn--active' : ''}`}
              onClick={() => handleViewModeChange('grid')}
              title="عرض شبكي"
              aria-label="عرض شبكي"
            >
              <LayoutGrid size={18} />
            </button>
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === 'list' ? 'view-toggle-btn--active' : ''}`}
              onClick={() => handleViewModeChange('list')}
              title="عرض قائمة"
              aria-label="عرض قائمة"
            >
              <List size={18} />
            </button>
          </div>
        </div>
      </div>

      {/* ── States ── */}
      {isLoading ? (
        <EventSkeletonGrid count={6} />
      ) : isError ? (
        <ErrorState onRetry={refetch} />
      ) : !filtered?.length ? (
        <EmptyState
          hasFilters={Boolean(searchQuery || statusFilter)}
          onCreate={() => setShowCreateDialog(true)}
          onClear={() => { setSearchQuery(''); setStatusFilter('') }}
        />
      ) : viewMode === 'grid' ? (
        <div className="events-grid">
          {filtered.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      ) : (
        <div className="events-list-container">
          <div className="events-list-header">
            <div className="events-list-header-col events-list-col--title">المناسبة</div>
            <div className="events-list-header-col events-list-col--date">التاريخ والوقت</div>
            <div className="events-list-header-col events-list-col--venue">المكان</div>
            <div className="events-list-header-col events-list-col--quota">حصة الحضور</div>
            <div className="events-list-header-col events-list-col--status">الحالة</div>
            <div className="events-list-header-col events-list-col--actions">الإجراءات</div>
          </div>
          <div className="events-list-body">
            {filtered.map((event) => {
              const { label, css } = getStatusConfig(event.status)
              const accent = event.theme_color ?? '#D4A32C'
              return (
                <div
                  key={event.id}
                  className="events-list-row"
                  onClick={() => navigate(`/events/${event.id}`)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && navigate(`/events/${event.id}`)}
                  aria-label={`عرض تفاصيل: ${event.title}`}
                >
                  {/* Title & Cover Image */}
                  <div className="events-list-row-col events-list-col--title">
                    <div
                      className="events-list-row-thumb"
                      style={{
                        backgroundImage: event.cover_image_url ? `url(${event.cover_image_url})` : undefined,
                        borderColor: `${accent}40`,
                      }}
                    >
                      {!event.cover_image_url && (
                        <CalendarDays size={16} style={{ color: accent }} />
                      )}
                    </div>
                    <div className="events-list-row-title-wrap">
                      <span className="events-list-row-title">{event.title}</span>
                      <span className="events-list-row-badge">
                        {event.allow_rsvp ? 'تأكيد الحضور' : 'دعوات مباشرة'}
                      </span>
                    </div>
                  </div>

                  {/* Date */}
                  <div className="events-list-row-col events-list-col--date">
                    <CalendarDays size={14} className="events-list-row-icon" />
                    <span>{formatDateShort(event.start_date)}</span>
                  </div>

                  {/* Venue */}
                  <div className="events-list-row-col events-list-col--venue">
                    {event.venue_name ? (
                      <span>
                        {event.venue_name}
                        {event.venue_city ? `، ${event.venue_city}` : ''}
                      </span>
                    ) : (
                      <span className="events-list-row-empty">—</span>
                    )}
                  </div>

                  {/* Quotas */}
                  <div className="events-list-row-col events-list-col--quota">
                    <div className="events-list-row-quotas">
                      {event.vip_quota > 0 && (
                        <span className="quota-tag quota-tag--vip">VIP: {event.vip_quota}</span>
                      )}
                      {event.normal_quota > 0 && (
                        <span className="quota-tag quota-tag--normal">عادي: {event.normal_quota}</span>
                      )}
                      {event.vip_quota === 0 && event.normal_quota === 0 && (
                        <span className="events-list-row-empty">—</span>
                      )}
                    </div>
                  </div>

                  {/* Status */}
                  <div className="events-list-row-col events-list-col--status">
                    <span className={`event-card__status status-badge--${css}`} style={{ position: 'static', backdropFilter: 'none' }}>
                      {label}
                    </span>
                  </div>

                  {/* Actions */}
                  <div className="events-list-row-col events-list-col--actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/events/${event.id}`)
                      }}
                    >
                      عرض التفاصيل
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Create Dialog ── */}
      {showCreateDialog && (
        <CreateEventDialog
          isOpen={showCreateDialog}
          onClose={() => setShowCreateDialog(false)}
        />
      )}
    </WorkspaceShell>
  )
}

// ── Error State ──────────────────────────────────────────────────
function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="events-empty-state">
      <div className="events-empty-state__icon">
        <CalendarDays size={36} />
      </div>
      <h3>فشل تحميل المناسبات</h3>
      <p>تعذّر الاتصال بالخادم. يُرجى التحقق من الاتصال والمحاولة مجدداً.</p>
      <button className="btn btn-ghost" onClick={onRetry}>
        <RefreshCw size={16} />
        إعادة المحاولة
      </button>
    </div>
  )
}

// ── Empty State ──────────────────────────────────────────────────
function EmptyState({
  hasFilters,
  onCreate,
  onClear,
}: {
  hasFilters: boolean
  onCreate: () => void
  onClear: () => void
}) {
  return (
    <div className="events-empty-state">
      <div className="events-empty-state__icon">
        <CalendarDays size={36} />
      </div>
      {hasFilters ? (
        <>
          <h3>لا توجد نتائج مطابقة</h3>
          <p>لم يتم العثور على مناسبات تطابق معايير البحث المحددة.</p>
          <button className="btn btn-ghost" onClick={onClear}>
            إلغاء الفلاتر
          </button>
        </>
      ) : (
        <>
          <h3>لا توجد مناسبات بعد</h3>
          <p>ابدأ بإنشاء أول فعالية أو مناسبة لمساحة العمل هذه.</p>
          <button className="btn btn-primary" onClick={onCreate}>
            <Plus size={16} />
            إنشاء مناسبة جديدة
          </button>
        </>
      )}
    </div>
  )
}
