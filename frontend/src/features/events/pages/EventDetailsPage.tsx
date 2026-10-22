/**
 * EventDetailsPage.tsx
 * Clean orchestrator for the event detail view.
 * All business logic lives in hooks; all UI lives in components.
 */
import { useState, useMemo, useEffect } from 'react'
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
      { id: 'analytics', permission: canAnalytics },
      { id: 'overview', permission: canOverview },
      { id: 'invitations', permission: canInvitations },
      { id: 'rsvp', permission: canRsvp },
      { id: 'registration', permission: canRegistration },
      { id: 'templates', permission: canTemplates },
      { id: 'barcodes', permission: canBarcodes },
      { id: 'final_invitations', permission: canFinal },
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
            {canAnalytics && (
              <button id="tab-analytics" className={`event-tab ${activeTab === 'analytics' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('analytics')} role="tab" tabIndex={activeTab === 'analytics' ? 0 : -1} aria-selected={activeTab === 'analytics'} aria-controls="panel-analytics">
                <BarChart3 size={15} /> الإحصائيات
              </button>
            )}
            {canOverview && (
              <button id="tab-overview" className={`event-tab ${activeTab === 'overview' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('overview')} role="tab" tabIndex={activeTab === 'overview' ? 0 : -1} aria-selected={activeTab === 'overview'} aria-controls="panel-overview">
                <Settings size={15} /> إعدادات المناسبة
              </button>
            )}
            {canInvitations && (
              <button id="tab-invitations" className={`event-tab ${activeTab === 'invitations' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('invitations')} role="tab" tabIndex={activeTab === 'invitations' ? 0 : -1} aria-selected={activeTab === 'invitations'} aria-controls="panel-invitations">
                <Printer size={15} /> إنشاء الدعوات
              </button>
            )}
            {canRsvp && (
              <button id="tab-rsvp" className={`event-tab ${activeTab === 'rsvp' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('rsvp')} role="tab" tabIndex={activeTab === 'rsvp' ? 0 : -1} aria-selected={activeTab === 'rsvp'} aria-controls="panel-rsvp">
                <CalendarCheck size={15} /> <span>ردود الضيوف</span>
              </button>
            )}
            {canRegistration && (
              <button id="tab-registration" className={`event-tab ${activeTab === 'registration' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('registration')} role="tab" tabIndex={activeTab === 'registration' ? 0 : -1} aria-selected={activeTab === 'registration'} aria-controls="panel-registration">
                <ClipboardList size={15} /> نموذج التسجيل
              </button>
            )}
            {canTemplates && (
              <button id="tab-templates" className={`event-tab ${activeTab === 'templates' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('templates')} role="tab" tabIndex={activeTab === 'templates' ? 0 : -1} aria-selected={activeTab === 'templates'} aria-controls="panel-templates">
                <Palette size={15} /> تصاميم الدعوات
              </button>
            )}
            {canBarcodes && (
              <button id="tab-barcodes" className={`event-tab ${activeTab === 'barcodes' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('barcodes')} role="tab" tabIndex={activeTab === 'barcodes' ? 0 : -1} aria-selected={activeTab === 'barcodes'} aria-controls="panel-barcodes">
                <QrCode size={15} /> عمليات إنشاء الدعوات
              </button>
            )}
            {canFinal && (
              <button id="tab-final_invitations" className={`event-tab ${activeTab === 'final_invitations' ? 'event-tab--active' : ''}`} onClick={() => setActiveTab('final_invitations')} role="tab" tabIndex={activeTab === 'final_invitations' ? 0 : -1} aria-selected={activeTab === 'final_invitations'} aria-controls="panel-final_invitations">
                <CheckCircle2 size={15} style={{ color: '#D4A32C' }} /> <span style={{ fontWeight: 'bold' }}>الدعوات الجاهزة للدخول</span>
              </button>
            )}
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
