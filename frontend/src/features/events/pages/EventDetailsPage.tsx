/**
 * EventDetailsPage.tsx
 * Clean orchestrator for the event detail view.
 * All business logic lives in hooks; all UI lives in components.
 */
import { Fragment, useState, useMemo, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { http } from '@services/http/client'
import { Can, PERM, usePermission } from '@shared/permissions'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { useAuthStore } from '@features/auth/store/authStore'
import {
  useEventDetail,
  useEventStats,
  useEventPublish,
  useEventDelete,
} from '../hooks/useEventDetails'
import { EventAnalyticsTab } from '../components/EventAnalyticsTab'
import { EventSettingsForm } from '../components/EventSettingsForm'
import { EventInvitationsTab } from '../components/EventInvitationsTab'
import { EventBarcodesTab } from '../components/EventBarcodesTab'
import { EventTemplatesTab } from '../components/EventTemplatesTab'
import { EventRsvpTab } from '../components/EventRsvpTab'
import { EventRegistrationTab } from '../components/EventRegistrationTab'
import { EventFinalInvitationsTab } from '../components/EventFinalInvitationsTab'
import { EventJourney, buildJourney, type JourneyTarget } from '../components/EventJourney'
import { templatesApi } from '../api/templatesApi'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { toast } from '@/components/toast'
import { getApiErrorMessage } from '@services/http/client'
import {
  Loader2,
  ArrowRight,
  Globe,
  Settings,
  CalendarDays,
  QrCode,
  Printer,
  Palette, CalendarCheck, ClipboardList, CheckCircle2,
  BarChart3, Trash2, PanelRightClose, PanelRightOpen,
} from 'lucide-react'
import '@features/users/pages/users.css'
import './events.css'

type Tab = 'analytics' | 'overview' | 'invitations' | 'final_invitations' | 'rsvp' | 'registration' | 'barcodes' | 'templates'

export default function EventDetailsPage() {
  const { eventId } = useParams<{ eventId: string }>()
  const navigate = useNavigate()
  const currentTenantId = useAuthStore((s) => s.currentTenantId)
  const currentUserId = useAuthStore((s) => s.user?.id)

  const [searchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab') as Tab | null
  const canAnalytics = usePermission(PERM.EVENT_TAB_ANALYTICS)
  const canOverview = usePermission(PERM.EVENT_TAB_SETTINGS)
  const canInvitations = usePermission(PERM.EVENT_TAB_INVITATIONS)
  const hasRsvpPermission = usePermission(PERM.EVENT_TAB_RSVP)
  const { data: rsvpAvailability } = useQuery({
    queryKey: ['feature-availability', currentTenantId, 'rsvp'],
    queryFn: () => http.get<{ enabled: boolean }>('/tenants/current/features/rsvp/availability').then(r => r.data),
    enabled: !!currentTenantId && hasRsvpPermission,
    staleTime: 0,
  })
  const canRsvp = hasRsvpPermission && rsvpAvailability?.enabled === true
  const canRegistration = usePermission(PERM.EVENT_TAB_REGISTRATION)
  const canTemplates = usePermission(PERM.EVENT_TAB_TEMPLATES)
  const canBarcodes = usePermission(PERM.EVENT_TAB_BARCODES)
  const canFinal = usePermission(PERM.EVENT_TAB_FINAL)

  const visibleTabs = useMemo(() => {
    const all: { id: Tab; permission: boolean }[] = [
      // Setup order first, then monitoring, then optional tools.
      { id: 'overview', permission: canOverview },
      { id: 'templates', permission: canTemplates },
      { id: 'invitations', permission: canInvitations },
      { id: 'barcodes', permission: canBarcodes },
      { id: 'final_invitations', permission: canFinal },
      { id: 'analytics', permission: canAnalytics },
      { id: 'registration', permission: canRegistration },
      { id: 'rsvp', permission: canRsvp },
    ]
    return all.filter(t => t.permission)
  }, [canAnalytics, canOverview, canInvitations, canRsvp, canRegistration, canTemplates, canBarcodes, canFinal])

  const defaultTab = visibleTabs[0]?.id ?? 'analytics'
  const initialTab = tabFromUrl && visibleTabs.some(t => t.id === tabFromUrl) ? tabFromUrl : defaultTab
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)
  const [sidebarHidden, setSidebarHidden] = useState(() => {
    try { return sessionStorage.getItem('qentry_event_sidebar_hidden') === 'true' }
    catch { return false }
  })

  useEffect(() => {
    try { sessionStorage.setItem('qentry_event_sidebar_hidden', String(sidebarHidden)) }
    catch { /* The toggle still works when browser storage is unavailable. */ }
  }, [sidebarHidden])

  useEffect(() => {
    if (!visibleTabs.some(t => t.id === activeTab)) {
      setActiveTab(defaultTab)
    }
  }, [activeTab, defaultTab, visibleTabs])
  const [showPublishConfirm, setShowPublishConfirm] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  // ── Data ──────────────────────────────────────────────────────
  const { data: event, isLoading } = useEventDetail(currentTenantId, eventId)
  const { data: stats, isLoading: isLoadingStats } = useEventStats(eventId)
  const publishMutation = useEventPublish(currentTenantId, eventId)
  const deleteMutation = useEventDelete(currentTenantId, eventId)
  const canPublish = usePermission(PERM.EVENT_PUBLISH)
  const { data: eventTemplates } = useQuery({
    queryKey: ['event-journey-templates', currentTenantId, eventId],
    queryFn: () => templatesApi.list(eventId!),
    enabled: Boolean(currentTenantId && eventId && canTemplates),
  })
  const journey = event ? buildJourney(event, stats, eventTemplates?.length ?? 0).map(step => ({
    ...step,
    locked: {
      overview: !canOverview, templates: !canTemplates, invitations: !canInvitations,
      publish: !canPublish, final_invitations: !canFinal, analytics: !canAnalytics,
    }[step.id],
  })) : []
  const landedOnJourney = useRef(false)
  // A first visit lands on the step that is due next instead of on empty statistics.
  useEffect(() => {
    if (landedOnJourney.current || !event || isLoadingStats || tabFromUrl) return
    landedOnJourney.current = true
    const next = journey.find(step => !step.done && !step.locked)
    const target: Tab = !next ? 'analytics' : next.id === 'publish' ? 'overview' : next.id
    if (visibleTabs.some(tab => tab.id === target)) setActiveTab(target)
  })

  const openJourneyStep = (id: JourneyTarget) => {
    if (id === 'publish') {
      if (event?.status === 'draft') setShowPublishConfirm(true)
      return
    }
    setActiveTab(id)
    setSidebarHidden(false)
    document.getElementById('event-section-navigation')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (!currentTenantId) {
    return (
      <WorkspaceShell title="لا توجد مساحة عمل" subtitle="">
        <div className="dash-state">
          <QrCode size={40} />
          <h1>لا توجد مساحة عمل محددة</h1>
          <p>اختر مساحة العمل أو سجّل الدخول من جديد لعرض بيانات المناسبة.</p>
          <div className="header-actions">
            <button className="btn btn-primary" onClick={() => navigate('/dashboard')}>
              العودة للوحة التحكم
            </button>
            <button className="btn btn-ghost" onClick={clearAuth}>
              تسجيل الخروج
            </button>
          </div>
        </div>
      </WorkspaceShell>
    )
  }

  // ── Loading ───────────────────────────────────────────────────
  if (isLoading) {
    return (
      <WorkspaceShell title="جاري التحميل…" subtitle="">
        <div className="center-loader" style={{ paddingTop: 80 }}>
          <Loader2 size={36} className="spin" />
          <span>جاري تحميل بيانات المناسبة…</span>
        </div>
      </WorkspaceShell>
    )
  }

  // ── Not Found ─────────────────────────────────────────────────
  if (!event) {
    return (
      <WorkspaceShell title="خطأ" subtitle="">
        <div className="events-empty-state">
          <CalendarDays size={48} style={{ opacity: 0.4 }} />
          <h3>المناسبة غير موجودة</h3>
          <p>ربما تم حذف هذه المناسبة أو أن الرابط غير صحيح.</p>
          <button className="btn btn-ghost" onClick={() => navigate('/events')}>
            <ArrowRight size={16} />
            العودة للمناسبات
          </button>
        </div>
      </WorkspaceShell>
    )
  }


  return (
    <WorkspaceShell
      title={event.title}
      subtitle="تفاصيل وإعدادات المناسبة"
      actions={
        <div className="header-actions">
          <button
            type="button"
            className="btn btn-ghost event-sidebar-toggle"
            title={sidebarHidden ? 'إظهار تبويبات المناسبة' : 'إخفاء تبويبات المناسبة'}
            aria-label={sidebarHidden ? 'إظهار تبويبات المناسبة' : 'إخفاء تبويبات المناسبة'}
            aria-expanded={!sidebarHidden}
            aria-controls="event-section-navigation"
            onClick={() => setSidebarHidden(hidden => !hidden)}
          >
            {sidebarHidden ? <PanelRightOpen size={18} /> : <PanelRightClose size={18} />}
          </button>
          {/* Publish Button — shown only when draft */}
          <Can permission={PERM.EVENT_PUBLISH}>
            {event.status === 'draft' && (
              <button
                className="btn btn-primary"
                onClick={() => setShowPublishConfirm(true)}
                disabled={publishMutation.isPending}
              >
                {publishMutation.isPending ? (
                  <Loader2 size={16} className="spin" />
                ) : (
                  <Globe size={16} />
                )}
                نشر المناسبة
              </button>
            )}
          </Can>

          <Can permission={PERM.EVENT_DELETE}>
            <button
              className="btn btn-danger"
              onClick={() => setShowDeleteConfirm(true)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <Trash2 size={16} />
              )}
              حذف المناسبة
            </button>
          </Can>

          {/* Back button */}
          <button className="btn btn-ghost" onClick={() => navigate('/events')}>
            عودة
            <ArrowRight size={16} style={{ marginRight: 6, marginLeft: 0 }} />
          </button>
        </div>
      }
    >
      <EventJourney steps={journey} onOpen={openJourneyStep} />
      <div className="event-details-layout">
        {/* Occasion section navigation */}
        <aside id="event-section-navigation" className="event-details-sidebar" hidden={sidebarHidden}>
          <div className="event-tabs" role="tablist" aria-label="أقسام المناسبة" aria-orientation="horizontal" onKeyDown={event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
            const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
            const index = tabs.indexOf(document.activeElement as HTMLButtonElement)
            if (index < 0 || !tabs.length) return
            event.preventDefault()
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowLeft' ? 1 : -1) + tabs.length) % tabs.length
            tabs[next].focus()
            tabs[next].click()
          }}>
            {([
              { id: 'overview', label: 'إعدادات المناسبة', icon: Settings, allowed: canOverview },
              { id: 'templates', label: 'تصاميم الدعوات', icon: Palette, allowed: canTemplates },
              { id: 'invitations', label: 'إنشاء الدعوات', icon: Printer, allowed: canInvitations },
              { id: 'barcodes', label: 'سجل عمليات الإنشاء', icon: QrCode, allowed: canBarcodes },
              { id: 'final_invitations', label: 'الدعوات الجاهزة للدخول', icon: CheckCircle2, allowed: canFinal },
              { id: 'analytics', label: 'الإحصائيات', icon: BarChart3, allowed: canAnalytics },
              { id: 'registration', label: 'نموذج التسجيل', icon: ClipboardList, allowed: canRegistration, optional: true },
              { id: 'rsvp', label: 'ردود الضيوف', icon: CalendarCheck, allowed: canRsvp, optional: true },
            ] as const).filter(tab => tab.allowed).map((tab, index, list) => {
              const Icon = tab.icon
              const active = activeTab === tab.id
              return (
                <Fragment key={tab.id}>
                  {'optional' in tab && !('optional' in (list[index - 1] ?? {})) && <span className="event-tabs__divider" role="presentation">أدوات إضافية</span>}
                  <button id={`tab-${tab.id}`} className={`event-tab ${active ? 'event-tab--active' : ''}`} onClick={() => setActiveTab(tab.id)} role="tab" tabIndex={active ? 0 : -1} aria-selected={active} aria-controls={`panel-${tab.id}`}>
                    <Icon size={15} /> {tab.label}
                  </button>
                </Fragment>
              )
            })}
          </div>
        </aside>

        {/* Active section content */}
        <div className="event-details-content">
          <div id="panel-analytics" role="tabpanel" aria-labelledby="tab-analytics" hidden={activeTab !== 'analytics'}>
            {activeTab === 'analytics' && (
              <EventAnalyticsTab event={event} stats={stats} isLoading={isLoadingStats} />
            )}
          </div>

          <div id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" hidden={activeTab !== 'overview'}>
            {activeTab === 'overview' && (
              <EventSettingsForm event={event} tenantId={currentTenantId} />
            )}
          </div>

          <div id="panel-invitations" role="tabpanel" aria-labelledby="tab-invitations" hidden={activeTab !== 'invitations'}>
            {activeTab === 'invitations' && (
              <EventInvitationsTab key={`${currentUserId}:${currentTenantId}:${event.id}`} event={event} stats={stats} />
            )}
          </div>

          <div id="panel-rsvp" role="tabpanel" aria-labelledby="tab-rsvp" hidden={activeTab !== 'rsvp'}>
            {canRsvp && activeTab === 'rsvp' && (
              <EventRsvpTab eventId={event.id} eventTitle={event.title} allowRsvp={event.allow_rsvp} />
            )}
          </div>

          <div id="panel-registration" role="tabpanel" aria-labelledby="tab-registration" hidden={activeTab !== 'registration'}>
            {activeTab === 'registration' && (
              <EventRegistrationTab event={event} isActiveTab={activeTab === 'registration'} />
            )}
          </div>

          <div id="panel-templates" role="tabpanel" aria-labelledby="tab-templates" hidden={activeTab !== 'templates'}>
            {activeTab === 'templates' && (
              <EventTemplatesTab eventId={event.id} event={event} isActiveTab={activeTab === 'templates'} />
            )}
          </div>

          <div id="panel-barcodes" role="tabpanel" aria-labelledby="tab-barcodes" hidden={activeTab !== 'barcodes'}>
            {activeTab === 'barcodes' && (
              <EventBarcodesTab event={event} stats={stats} onlyHistory />
            )}
          </div>

          <div id="panel-final_invitations" role="tabpanel" aria-labelledby="tab-final_invitations" hidden={activeTab !== 'final_invitations'}>
            {activeTab === 'final_invitations' && (
              <EventFinalInvitationsTab event={event} stats={stats} />
            )}
          </div>
        </div>
      </div>

      {/* ── Publish Confirmation ── */}
      <ConfirmDialog
        isOpen={showPublishConfirm}
        title="نشر المناسبة"
        message={`هل أنت متأكد من نشر مناسبة "${event.title}"؟ بعد النشر، سيتمكن الضيوف من رؤية الدعوات وتأكيد حضورهم.`}
        confirmLabel="نعم، انشر الآن"
        variant="default"
        isPending={publishMutation.isPending}
        onConfirm={() => {
          publishMutation.mutate(undefined, {
            onSuccess: () => setShowPublishConfirm(false),
            onError: (error) => {
              setShowPublishConfirm(false)
              toast.error(
                'تعذر نشر المناسبة',
                getApiErrorMessage(error, 'راجع إعدادات المناسبة ثم حاول مرة أخرى.'),
              )
            },
          })
        }}
        onCancel={() => setShowPublishConfirm(false)}
      />

      {/* ── Delete Confirmation ── */}
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        title="حذف المناسبة"
        message={`هل أنت متأكد من حذف مناسبة "${event.title}"؟ هذا الإجراء نهائي وسيؤدي لحذف جميع الضيوف والدعوات المرتبطة به ولا يمكن التراجع عنه.`}
        confirmLabel="نعم، احذف المناسبة"
        variant="danger"
        isPending={deleteMutation.isPending}
        onConfirm={() => {
          deleteMutation.mutate(undefined, {
            onSuccess: () => {
              setShowDeleteConfirm(false)
              navigate('/events')
            },
          })
        }}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </WorkspaceShell>
  )
}
