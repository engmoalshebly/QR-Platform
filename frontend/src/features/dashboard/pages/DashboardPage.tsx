import { useMemo, useState, useEffect } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity,
  BarChart3,
  CalendarDays,
  Clock3,
  MailCheck,
  QrCode,
  RefreshCcw,
  Crown,
  Ticket,
  Users,
  TrendingUp,
  Zap,
  CheckCircle2,
  UserCheck,
  MessageCircleReply,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react'
import { dashboardAPI } from '../api/dashboardApi'
import { useAuthStore } from '@features/auth/store/authStore'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { PERM, usePermission } from '@shared/permissions'
import { StatCard } from '../components/StatCard'
import { MiniDonutChart } from '../components/MiniDonutChart'
import { ActivityTimeline } from '../components/ActivityTimeline'
import { MemberAvatarStack } from '../components/MemberAvatarStack'
import { SubscriptionCard } from '../components/SubscriptionCard'
import { TopEventsTable } from '../components/TopEventsTable'
import { UsageGauge } from '../components/UsageGauge'
import { LoadingState } from '@components/UiStates'
import type { DashboardAnalytics } from '../types'
import './dashboard.css'

/* ── Formatters ── */
const numberFmt = new Intl.NumberFormat('ar')

function n(value?: number | null) {
  return numberFmt.format(Number(value || 0))
}

function pct(part?: number, total?: number) {
  if (!total) return 0
  return Math.min(100, Math.round(((part || 0) / total) * 100))
}

function getGreeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'صباح الخير'
  if (h < 17) return 'مساء الخير'
  return 'مساء النور'
}

/* ── Section Header ── */
function SectionHeader({ icon: Icon, kicker, title }: { icon: typeof BarChart3; kicker: string; title: string }) {
  return (
    <div className="dash-section-head">
      <div>
        <span className="dash-kicker">{kicker}</span>
        <h2>{title}</h2>
      </div>
      <Icon size={20} className="dash-section-head__icon" />
    </div>
  )
}

/* ── Progress Row ── */
function ProgressRow({ label, value, total, color }: { label: string; value: number; total: number; color?: string }) {
  const percentage = pct(value, total)
  return (
    <div className="progress-row">
      <div className="progress-row__meta">
        <span>{label}</span>
        <strong>{n(value)} / {n(total)}</strong>
      </div>
      <div className="progress-row__track">
        <motion.span
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 0.8, ease: [0, 0, 0.2, 1], delay: 0.3 }}
          style={color ? { background: color } : undefined}
        />
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════
   ██ DASHBOARD CONTENT
   ══════════════════════════════════════════════════════════════ */

function DashboardContent({ data }: { data: DashboardAnalytics }) {
  const totalInvitations = data.invitations.total_invitations || 0
  const checkedIn = data.invitations.checked_in_invitations || 0
  const checkinRate = pct(checkedIn, totalInvitations)
  const openedRate = pct(data.invitations.opened_invitations, totalInvitations)
  const responseRate = pct(
    (data.invitations.accepted_invitations || 0) + (data.invitations.declined_invitations || 0) + (data.invitations.maybe_invitations || 0),
    totalInvitations,
  )
  const invitationTrend = data.daily_trend?.map(point => Number(point.invitations)) || []
  const checkinTrend = data.daily_trend?.map(point => Number(point.checkins)) || []
  const eventTrend = data.daily_trend?.map(point => Number(point.events)) || []

  const greeting = useMemo(() => getGreeting(), [])

  const donutSegments = useMemo(() => [
    { value: data.invitations.opened_invitations || 0, color: '#D4A32C', label: 'مفتوح' },
    { value: (data.invitations.delivered_invitations || 0) - (data.invitations.opened_invitations || 0), color: '#3B82F6', label: 'مُسلم' },
    { value: (data.invitations.sent_invitations || 0) - (data.invitations.delivered_invitations || 0), color: '#64748B', label: 'مُرسل' },
  ].filter(s => s.value > 0), [data.invitations])

  const usageItems = useMemo(() => {
    if (data.usage.length) return data.usage.slice(0, 4)
    return [
      { key: 'الأحداث', value: data.events.total_events || 0 },
      { key: 'الدعوات', value: totalInvitations },
      { key: 'الأعضاء', value: data.members.total_members || 0 },
    ]
  }, [data, totalInvitations])
  const relativeUsageMax = Math.max(100, ...usageItems.map(item => Number(item.value || 0)))

  return (
    <WorkspaceShell
      title={`${greeting} 👋`}
      subtitle={`${data.tenant?.name || 'مساحة العمل'} · ${data.tenant?.slug || 'tenant'}`}
      actions={
        <>
          <span className="dash-pill"><Crown size={16} />{data.subscription?.plan_name || data.tenant?.plan || 'Free'}</span>
          <button className="dash-icon-btn" onClick={() => window.location.reload()} aria-label="تحديث">
            <RefreshCcw size={18} />
          </button>
        </>
      }
    >
      {data.linked_organizer && (
        <section className="dash-linked-organizer" aria-label="نطاق لوحة التحكم">
          <Users size={18} />
          <div>
            <strong>نظرة موحّدة للمؤسسة وفريق التنظيم</strong>
            <span>تشمل مؤشرات الأحداث والدعوات العمليات المسندة إلى {data.linked_organizer.name} أيضاً.</span>
          </div>
        </section>
      )}

      {/* ═══ KPI STAT CARDS ═══ */}
      <section className="dash-stats-grid" aria-label="مؤشرات الأداء">
        <StatCard
          title="الأحداث"
          value={data.events.total_events || 0}
          delta={`${n(data.events.active_events)} نشط`}
          deltaType="positive"
          icon={CalendarDays}
          tone="gold"
          sparkData={eventTrend}
          index={0}
        />
        <StatCard
          title="الدعوات"
          value={totalInvitations}
          delta={`${n(data.invitations.sent_invitations)} مرسل`}
          deltaType="neutral"
          icon={Ticket}
          tone="blue"
          sparkData={invitationTrend}
          index={1}
        />
        <StatCard
          title="تسجيل الحضور"
          value={checkinRate}
          formatted={`${checkinRate}%`}
          delta={`${n(checkedIn)} حضور مؤكد`}
          deltaType="positive"
          icon={QrCode}
          tone="green"
          sparkData={checkinTrend}
          index={2}
        />
        <StatCard
          title="الفريق"
          value={data.members.total_members || 0}
          delta={`${n(data.members.active_members)} عضو نشط`}
          deltaType="neutral"
          icon={Users}
          tone="purple"
          index={3}
        />
      </section>

      <section className="dash-kpi-strip" aria-label="مؤشرات المؤسسة التفصيلية">
        <div><CheckCircle2 size={18} /><span>تأكيد الحضور</span><strong>{pct(data.invitations.accepted_invitations, totalInvitations)}%</strong><small>{n(data.invitations.accepted_invitations)} دعوة</small></div>
        <div><MessageCircleReply size={18} /><span>معدل الاستجابة</span><strong>{responseRate}%</strong><small>{n(data.invitations.pending_invitations)} بانتظار الرد</small></div>
        <div><UserCheck size={18} /><span>الأشخاص الحاضرون</span><strong>{n(data.invitations.checked_in_people)}</strong><small>من {n(data.invitations.invited_people)} متوقع</small></div>
        <div><ShieldCheck size={18} /><span>جودة المسح</span><strong>{Number(data.checkin_quality?.scan_success_rate || 0)}%</strong><small>{n(data.checkin_quality?.total_scans)} عملية مسح</small></div>
      </section>

      {/* ═══ PRIMARY GRID: Performance + Subscription ═══ */}
      <section className="dash-bento dash-bento--primary">
        {/* ── Performance Panel ── */}
        <motion.div
          className="dash-panel dash-panel--wide"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.35 }}
        >
          <SectionHeader icon={BarChart3} kicker="الأداء العام" title="مؤشرات الدعوات والحضور" />

          <div className="performance-grid">
            <div className="performance-bars">
              <ProgressRow label="فتح الدعوات" value={data.invitations.opened_invitations || 0} total={totalInvitations} color="#D4A32C" />
              <ProgressRow label="الدعوات المسلمة" value={data.invitations.delivered_invitations || 0} total={totalInvitations} color="#3B82F6" />
              <ProgressRow label="الحضور المسجل" value={checkedIn} total={totalInvitations} color="#22C55E" />
            </div>
            <div className="performance-donut">
              <MiniDonutChart
                segments={donutSegments}
                size={140}
                strokeWidth={14}
                centerValue={`${openedRate}%`}
                centerLabel="معدل الفتح"
              />
            </div>
          </div>

          <div className="dash-split-metrics">
            <div>
              <strong>{openedRate}%</strong>
              <span>معدل الفتح</span>
            </div>
            <div>
              <strong>{n(data.templates.total_templates)}</strong>
              <span>قوالب</span>
            </div>
            <div>
              <strong>{n(data.audit.audit_7d)}</strong>
              <span>نشاط خلال 7 أيام</span>
            </div>
          </div>
        </motion.div>

        {/* ── Subscription Panel ── */}
        <SubscriptionCard
          subscription={data.subscription}
          planFallback={data.tenant?.plan}
        />
      </section>

      <section className="dash-bento dash-bento--analytics">
        <motion.div className="dash-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <SectionHeader icon={MessageCircleReply} kicker="مسار الدعوة" title="التحويل والاستجابة" />
          <div className="analytics-funnel">
            <ProgressRow label="إجمالي الدعوات" value={totalInvitations} total={totalInvitations} color="#D4A32C" />
            <ProgressRow label="تم الإرسال" value={data.invitations.sent_invitations || 0} total={totalInvitations} color="#3B82F6" />
            <ProgressRow label="تم التسليم" value={data.invitations.delivered_invitations || 0} total={totalInvitations} color="#60A5FA" />
            <ProgressRow label="تم الفتح" value={data.invitations.opened_invitations || 0} total={totalInvitations} color="#A78BFA" />
            <ProgressRow label="تم التأكيد" value={data.invitations.accepted_invitations || 0} total={totalInvitations} color="#22C55E" />
          </div>
        </motion.div>

        <motion.div className="dash-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <SectionHeader icon={ShieldCheck} kicker="جودة التشغيل" title="تحليل عمليات الدخول" />
          <div className="quality-grid">
            <div className="quality-hero"><strong>{Number(data.checkin_quality?.scan_success_rate || 0)}%</strong><span>نسبة نجاح المسح</span></div>
            <div><strong>{n(data.checkin_quality?.successful_scans)}</strong><span>ناجحة</span></div>
            <div><strong>{n(data.checkin_quality?.duplicate_scans)}</strong><span>مكررة</span></div>
            <div><strong>{n(data.checkin_quality?.rejected_scans)}</strong><span>مرفوضة</span></div>
            <div><strong>{n(data.checkin_quality?.scans_today)}</strong><span>اليوم</span></div>
            <div><strong>{n(data.checkin_quality?.scans_7d)}</strong><span>آخر 7 أيام</span></div>
          </div>
          {(data.checkin_quality?.duplicate_scans || 0) + (data.checkin_quality?.rejected_scans || 0) > 0 && (
            <p className="quality-alert"><AlertTriangle size={15} /> توجد محاولات تحتاج مراجعة تشغيلية.</p>
          )}
        </motion.div>

        <motion.div className="dash-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <SectionHeader icon={CalendarDays} kicker="محفظة الأحداث" title="توزيع الحالات" />
          <div className="status-distribution">
            {(data.event_status_distribution || []).map(item => {
              const labels: Record<string, string> = { draft: 'مسودة', published: 'منشور', active: 'نشط', completed: 'مكتمل', cancelled: 'ملغي' }
              return <div key={item.status}><span>{labels[item.status] || item.status}</span><strong>{n(item.count)}</strong><i style={{ width: `${pct(item.count, data.events.total_events)}%` }} /></div>
            })}
            {!data.event_status_distribution?.length && <p className="analytics-empty">لا توجد أحداث بعد</p>}
          </div>
        </motion.div>
      </section>

      {/* ═══ SECONDARY GRID: Events + Usage + Team ═══ */}
      <section className="dash-bento dash-bento--secondary">
        {/* ── Top Events ── */}
        <motion.div
          className="dash-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.45 }}
        >
          <SectionHeader icon={TrendingUp} kicker="الأحداث الأعلى" title="حسب حجم الدعوات" />
          <TopEventsTable events={data.top_events} />
        </motion.div>

        {/* ── Usage ── */}
        <motion.div
          className="dash-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.5 }}
        >
          <SectionHeader icon={Zap} kicker="الاستخدام" title="حجم النشاط هذا الشهر" />
          <div className="usage-gauges">
            {usageItems.map((item) => (
              <UsageGauge
                key={item.key}
                label={item.key.replace(/_/g, ' ')}
                value={item.value}
                max={relativeUsageMax}
              />
            ))}
          </div>
          <p className="usage-caption">مقارنة نسبية بين أنواع النشاط، وليست نسبة من حد الباقة.</p>
        </motion.div>

        {/* ── Team ── */}
        <motion.div
          className="dash-panel"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.55 }}
        >
          <SectionHeader icon={Users} kicker="الفريق" title="الأعضاء" />
          <MemberAvatarStack members={data.members_list} />
        </motion.div>
      </section>

      {/* ═══ ACTIVITY TIMELINE ═══ */}
      <motion.section
        className="dash-panel"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.6 }}
      >
        <SectionHeader icon={Clock3} kicker="النشاط الأخير" title="سجل العمليات" />
        <ActivityTimeline items={data.recent_activity} />
      </motion.section>
    </WorkspaceShell>
  )
}

/* ══════════════════════════════════════════════════════════════
   ██ DASHBOARD PAGE (Root)
   ══════════════════════════════════════════════════════════════ */

export default function DashboardPage() {
  const clearAuth = useAuthStore(s => s.clearAuth)
  const currentTenantId = useAuthStore(s => s.currentTenantId)

  // Success states and URL params interceptor for upgraded subscriptions
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [showUpgradeSuccess, setShowUpgradeSuccess] = useState(false)
  const [upgradedPlan, setUpgradedPlan] = useState('')

  useEffect(() => {
    if (searchParams.get('upgrade_success') === 'true') {
      const plan = searchParams.get('plan') || ''
      setUpgradedPlan(plan)
      setShowUpgradeSuccess(true)

      // Invalidate dashboard analytics, settings usage, and tenant details
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['settings-usage', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['settings-tenant', currentTenantId] })

      // Clear parameters from search history cleanly
      const newParams = new URLSearchParams(searchParams)
      newParams.delete('upgrade_success')
      newParams.delete('plan')
      setSearchParams(newParams, { replace: true })
    }
  }, [searchParams, setSearchParams, queryClient, currentTenantId])

  // Permission checks
  const hasDashboardAccess = usePermission(PERM.NAV_DASHBOARD)
  const canEvents = usePermission(PERM.NAV_EVENTS)
  const canUsers = usePermission(PERM.NAV_USERS)
  const canTeams = usePermission(PERM.NAV_TEAMS)
  const canSettings = usePermission(PERM.NAV_SETTINGS)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['dashboard', currentTenantId],
    queryFn: dashboardAPI.analytics,
    enabled: Boolean(currentTenantId && hasDashboardAccess),
  })

  if (!currentTenantId) {
    return (
      <div className="dash-state">
        <div className="dash-state__icon-wrap">
          <MailCheck size={34} />
        </div>
        <h1>لا توجد مساحة عمل محددة</h1>
        <p>سجّل الدخول مرة أخرى لاختيار مساحة العمل.</p>
        <button onClick={clearAuth}>تسجيل الخروج</button>
      </div>
    )
  }

  // Redirect if no dashboard access
  if (!hasDashboardAccess) {
    if (canEvents) return <Navigate to="/events" replace />
    if (canUsers) return <Navigate to="/users" replace />
    if (canTeams) return <Navigate to="/teams" replace />
    if (canSettings) return <Navigate to="/settings" replace />

    // Fallback: Show a friendly welcome page wrapped in WorkspaceShell
    return (
      <WorkspaceShell title="مرحباً بك" subtitle="مساحة العمل الخاصة بك">
        <div className="dash-state" style={{ minHeight: 'calc(100vh - 200px)' }}>
          <div className="dash-state__icon-wrap">
            <Crown size={34} />
          </div>
          <h1>مرحباً بك في دعوة</h1>
          <p>ليس لديك صلاحيات كافية لعرض لوحة التحكم. يرجى استخدام القائمة الجانبية أو التواصل مع مسؤول النظام.</p>
        </div>
      </WorkspaceShell>
    )
  }

  if (isLoading) {
    return (
      <WorkspaceShell title="لوحة التحكم" subtitle="جار التحميل...">
        <LoadingState label="جار تحميل لوحة التحكم…" />
      </WorkspaceShell>
    )
  }

  if (isError || !data) {
    return (
      <WorkspaceShell title="لوحة التحكم" subtitle="خطأ في تحميل البيانات">
        <div className="dash-state" style={{ minHeight: 'calc(100vh - 200px)' }}>
          <div className="dash-state__icon-wrap dash-state__icon-wrap--error">
            <Activity size={34} />
          </div>
          <h1>تعذر تحميل البيانات</h1>
          <p>تحقق من اتصال الـ API ومساحة العمل الحالية.</p>
          <button onClick={() => refetch()} className="btn btn-primary" style={{ margin: '12px auto' }}>إعادة المحاولة</button>
        </div>
      </WorkspaceShell>
    )
  }

  return (
    <>
      <DashboardContent data={data} />

      <AnimatePresence>
        {showUpgradeSuccess && (
          <motion.div
            className="dialog-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{ zIndex: 1100 }}
            onClick={() => setShowUpgradeSuccess(false)}
          >
            <motion.div
              className="confirm-dialog"
              initial={{ opacity: 0, scale: 0.92, y: 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.92, y: 12 }}
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
              style={{ textAlign: 'center', padding: '40px 32px' }}
            >
              <div
                className="confirm-dialog__icon"
                style={{
                  background: 'rgba(212, 163, 44, 0.15)',
                  color: '#D4A32C',
                  width: '64px',
                  height: '64px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 24px',
                }}
              >
                <Crown size={32} />
              </div>

              <h3 className="confirm-dialog__title" style={{ fontSize: '24px', marginBottom: '12px', color: '#f8fafc' }}>
                تهانينا! تم ترقية باقتك بنجاح 🎉
              </h3>

              <p className="confirm-dialog__message" style={{ fontSize: '15px', color: '#94a3b8', lineHeight: '1.6', marginBottom: '32px' }}>
                تم تفعيل باقة <strong style={{ color: '#D4A32C', textTransform: 'capitalize' }}>{upgradedPlan}</strong> بنجاح لمساحة العمل الخاصة بك. يمكنك الآن الاستمتاع بحدود استخدام أعلى وميزات متقدمة فوراً!
              </p>

              <button
                className="btn btn-primary"
                onClick={() => setShowUpgradeSuccess(false)}
                style={{ width: '100%', padding: '12px', fontSize: '15px' }}
              >
                البدء في استخدام الميزات الجديدة
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
