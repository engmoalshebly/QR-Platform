import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart3, Building2, Users, CreditCard, FileText, Shield,
  TrendingUp, DollarSign, UserPlus, Calendar, Globe,
  Search, Ban, CheckCircle2, XCircle,
  RefreshCcw, Crown, Zap,
  Package, Settings2, LogOut, Sun, Moon, ArrowRight, ChevronLeft,
  Activity, Ticket, UserRoundCheck,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { platformAPI } from '../api/platformApi'
import { PlatformRolesTab } from '../components/PlatformRolesTab'
import type {
  PlatformAnalytics, PlanOverviewItem, AddonItem, PlatformTenant, OrgRequest,
  SubscriptionRequest, PendingCustomPlan,
} from '../api/platformApi'
import { useAuthStore } from '@features/auth/store/authStore'
import { useAdminTheme } from '@app/theme/ThemeProvider'
import { formatYer } from '@shared/utils/currency'
import './platform.css'

/* ── Number formatter ── */
const nf = new Intl.NumberFormat('ar-SA')
const cf = new Intl.NumberFormat('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
function n(v?: number | null) { return nf.format(v || 0) }
// Plans are priced in USD (migration_v69); YER is a display-only estimate
// for staff matching a manual bank-transfer amount against a USD price.
function currency(v?: number | null) { return `$${cf.format(v || 0)}` }
function currencyWithYer(v?: number | null) { return `$${cf.format(v || 0)} (≈ ${formatYer(v || 0)} ر.ي)` }
function dateTime(value?: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('ar-SA', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/* ── Tab definitions ── */
type TabKey = 'overview' | 'team_requests' | 'tenants' | 'users' | 'roles' | 'plans' | 'subscriptions' | 'audit'

const TABS: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [
  { key: 'overview',      label: 'نظرة عامة',  icon: BarChart3 },
  { key: 'team_requests', label: 'طلبات الفرق', icon: FileText },
  { key: 'tenants',       label: 'المؤسسات',   icon: Building2 },
  { key: 'users',         label: 'مديرو المنصة', icon: Users },
  { key: 'roles',         label: 'الأدوار',    icon: Shield },
  { key: 'plans',         label: 'الباقات',    icon: Package },
  { key: 'subscriptions', label: 'الاشتراكات', icon: CreditCard },
  { key: 'audit',         label: 'السجلات',    icon: FileText },
]

const STATUS_COLORS: Record<string, string> = {
  active: '#22c55e', trial: '#3b82f6', suspended: '#f59e0b', cancelled: '#ef4444', deleted: '#6b7280',
  draft: '#64748b', planning: '#f59e0b', published: '#3b82f6', completed: '#22c55e',
  pending: '#f59e0b', approved: '#22c55e', rejected: '#ef4444',
}

const STATUS_LABELS: Record<string, string> = {
  active: 'نشط', trial: 'تجريبي', suspended: 'معلّق', cancelled: 'ملغى',
  draft: 'مسودة', planning: 'قيد التخطيط', published: 'منشور', completed: 'مكتمل',
  pending: 'قيد المراجعة', approved: 'مقبول', rejected: 'مرفوض',
}

/* ══════════════════════════════════════════════════
   KPI Card
   ══════════════════════════════════════════════════ */
function KpiCard({ title, value, subtitle, icon: Icon, color, delay = 0 }: {
  title: string; value: string; subtitle?: string; icon: typeof TrendingUp; color: string; delay?: number
}) {
  return (
    <motion.div
      className="plat-kpi"
      initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay }}
    >
      <div className="plat-kpi__icon" style={{ background: `${color}18`, color }}><Icon size={20} /></div>
      <div className="plat-kpi__body">
        <span className="plat-kpi__title">{title}</span>
        <strong className="plat-kpi__value">{value}</strong>
        {subtitle && <span className="plat-kpi__sub">{subtitle}</span>}
      </div>
    </motion.div>
  )
}

/* ══════════════════════════════════════════════════
   Mini Bar Chart (plan distribution)
   ══════════════════════════════════════════════════ */
function PlanDistChart({ data }: { data: PlatformAnalytics['plan_distribution'] }) {
  const max = Math.max(...data.map(d => d.count), 1)
  return (
    <div className="plat-plan-chart">
      {data.map((d) => (
        <div key={d.plan} className="plat-plan-chart__bar-group">
          <div className="plat-plan-chart__bar-wrap">
            <motion.div
              className="plat-plan-chart__bar"
              style={{ background: d.badge_color || '#6b7280' }}
              initial={{ height: 0 }} animate={{ height: `${Math.max((d.count / max) * 100, 4)}%` }}
              transition={{ duration: 0.6, delay: 0.2 }}
            />
          </div>
          <span className="plat-plan-chart__label">{d.plan_name}</span>
          <span className="plat-plan-chart__count">{d.count}</span>
        </div>
      ))}
    </div>
  )
}

/* ══════════════════════════════════════════════════
   Trend Sparkline
   ══════════════════════════════════════════════════ */
function TrendSparkline({ data, color = '#C9A96E' }: { data: { date: string; value: number }[]; color?: string }) {
  if (!data.length) return null
  const max = Math.max(...data.map(d => d.value), 1)
  const w = 300; const h = 60; const pad = 4
  const points = data.map((d, i) => ({
    x: pad + (i / Math.max(data.length - 1, 1)) * (w - pad * 2),
    y: h - pad - (d.value / max) * (h - pad * 2)
  }))
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="plat-sparkline" preserveAspectRatio="none">
      <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={color} stopOpacity="0.3" />
        <stop offset="100%" stopColor={color} stopOpacity="0" />
      </linearGradient></defs>
      <path d={`${pathD} L${points[points.length - 1]!.x},${h} L${points[0].x},${h} Z`} fill="url(#sg)" />
      <path d={pathD} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/* ══════════════════════════════════════════════════
   STATUS BADGE
   ══════════════════════════════════════════════════ */
function StatusBadge({ status }: { status: string }) {
  return (
    <span className="plat-badge" style={{
      background: `${STATUS_COLORS[status] || '#6b7280'}20`,
      color: STATUS_COLORS[status] || '#6b7280',
      borderColor: `${STATUS_COLORS[status] || '#6b7280'}40`,
    }}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}

/* ══════════════════════════════════════════════════
   TAB: OVERVIEW
   ══════════════════════════════════════════════════ */
function OverviewTab({ data }: { data: PlatformAnalytics }) {
  const k = data.kpis; const r = data.revenue
  return (
    <div className="plat-overview">
      {/* KPIs Row */}
      <div className="plat-kpis-grid">
        <KpiCard title="المؤسسات" value={n(k.total_tenants)} subtitle={`${n(k.new_tenants_30d)} جديد (30 يوم)`} icon={Building2} color="#8b5cf6" delay={0} />
        <KpiCard title="المستخدمين" value={n(k.total_users)} subtitle={`${n(k.new_users_30d)} جديد (30 يوم)`} icon={Users} color="#3b82f6" delay={0.05} />
        <KpiCard title="الإيرادات الشهرية" value={currency(r.mrr)} subtitle={`${n(r.paying_tenants)} مشترك مدفوع`} icon={DollarSign} color="#22c55e" delay={0.1} />
        <KpiCard title="الإيرادات السنوية" value={currency(r.arr)} subtitle={`متوسط ${currency(r.avg_revenue_per_tenant)}/مؤسسة`} icon={TrendingUp} color="#C9A96E" delay={0.15} />
        <KpiCard title="الاشتراكات النشطة" value={n(k.active_subscriptions)} subtitle={`${n(k.trial_tenants)} تجريبي`} icon={CreditCard} color="#f59e0b" delay={0.2} />
        <KpiCard title="الأحداث" value={n(k.total_events)} subtitle={`${n(k.total_invitations)} دعوة`} icon={Calendar} color="#ec4899" delay={0.25} />
      </div>

      {/* Charts Row */}
      <div className="plat-charts-grid">
        {/* Plan Distribution */}
        <motion.div className="plat-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <div className="plat-panel__head"><Package size={18} /><h3>توزيع الباقات</h3></div>
          <PlanDistChart data={data.plan_distribution} />
        </motion.div>

        {/* Trend */}
        <motion.div className="plat-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
          <div className="plat-panel__head"><TrendingUp size={18} /><h3>اتجاه النمو (30 يوم)</h3></div>
          <div className="plat-trend-legends">
            <span><span className="plat-dot" style={{ background: '#8b5cf6' }} />مؤسسات</span>
            <span><span className="plat-dot" style={{ background: '#3b82f6' }} />مستخدمين</span>
          </div>
          <TrendSparkline data={data.trend_30d.map(t => ({ date: t.date, value: t.new_tenants }))} color="#8b5cf6" />
          <TrendSparkline data={data.trend_30d.map(t => ({ date: t.date, value: t.new_users }))} color="#3b82f6" />
        </motion.div>

        {/* Status Distribution */}
        <motion.div className="plat-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
          <div className="plat-panel__head"><Shield size={18} /><h3>حالات المؤسسات</h3></div>
          <div className="plat-status-list">
            {data.status_distribution.map(s => (
              <div key={s.status} className="plat-status-row">
                <StatusBadge status={s.status} />
                <strong>{n(s.count)}</strong>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Recent & Top */}
      <div className="plat-dual-grid">
        <motion.div className="plat-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 }}>
          <div className="plat-panel__head"><UserPlus size={18} /><h3>آخر المؤسسات المسجلة</h3></div>
          <table className="plat-table"><thead><tr><th>الاسم</th><th>الباقة</th><th>الحالة</th><th>الأعضاء</th></tr></thead>
            <tbody>{data.recent_tenants.map(t => (
              <tr key={t.id}><td>{t.name}</td><td><span className="plat-plan-tag">{t.plan}</span></td><td><StatusBadge status={t.status} /></td><td>{t.members_count}</td></tr>
            ))}</tbody>
          </table>
        </motion.div>

        <motion.div className="plat-panel" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
          <div className="plat-panel__head"><Zap size={18} /><h3>الأكثر نشاطاً</h3></div>
          <table className="plat-table"><thead><tr><th>الاسم</th><th>الأحداث</th><th>الدعوات</th><th>الأعضاء</th></tr></thead>
            <tbody>{data.top_tenants.map(t => (
              <tr key={t.id}><td>{t.name}</td><td>{n(t.events_count)}</td><td>{n(t.invitations_count)}</td><td>{n(t.members_count)}</td></tr>
            ))}</tbody>
          </table>
        </motion.div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════
   TAB: TENANTS
   ══════════════════════════════════════════════════ */
type TenantDetailTab = 'overview' | 'members' | 'roles' | 'activity'

function TenantDetailPage({ tenantId, onBack }: { tenantId: string; onBack: () => void }) {
  const [detailTab, setDetailTab] = useState<TenantDetailTab>('overview')
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['platform-tenant-detail', tenantId],
    queryFn: () => platformAPI.getTenant(tenantId),
  })

  if (isLoading) return <div className="plat-loading">جار تحميل ملف المؤسسة...</div>
  if (isError || !data) return <div className="plat-empty">تعذر تحميل ملف المؤسسة. <button className="plat-link-btn" onClick={() => refetch()}>إعادة المحاولة</button></div>

  const { tenant, workspace_group: workspaceGroup, subscription, analytics, members, roles, recent_events: recentEvents, recent_activity: recentActivity } = data
  const tabs: { key: TenantDetailTab; label: string; count?: number }[] = [
    { key: 'overview', label: 'نظرة عامة' },
    { key: 'members', label: 'الأعضاء', count: members.length },
    { key: 'roles', label: 'الأدوار', count: roles.length },
    { key: 'activity', label: 'سجل النشاط', count: analytics.activity_30d },
  ]

  return (
    <section className="plat-tenant-detail">
      <button className="plat-back-button" onClick={onBack}><ArrowRight size={17} />العودة إلى المؤسسات</button>
      <div className="plat-tenant-hero">
        <div className="plat-tenant-hero__identity">
          <div className="plat-tenant-hero__icon"><Building2 size={24} /></div>
          <div>
            <span>{workspaceGroup.is_linked ? 'مؤسسة موحّدة' : 'ملف المؤسسة'}</span>
            <h2>{tenant.name}</h2>
            <p className="plat-mono">{tenant.slug}</p>
          </div>
        </div>
        <div className="plat-tenant-hero__meta">
          <StatusBadge status={tenant.status} />
          {workspaceGroup.is_linked && <span className="plat-unified-badge">تشغيل + فعاليات</span>}
          <span className="plat-plan-tag">{subscription?.plan_name || tenant.plan}</span>
          <span>أنشئت {dateTime(tenant.created_at)}</span>
        </div>
      </div>

      <div className="plat-kpis-grid plat-kpis-grid--tenant">
        <KpiCard title="الأعضاء النشطون" value={n(tenant.members_count)} subtitle={`${n(members.length)} عضو إجمالاً`} icon={Users} color="#3b82f6" />
        <KpiCard title="الفعاليات" value={n(analytics.events_total)} subtitle={`${n(analytics.events_upcoming)} قادمة`} icon={Calendar} color="#8b5cf6" delay={0.05} />
        <KpiCard title="الدعوات" value={n(analytics.invitations_total)} subtitle={`${n(analytics.vip_capacity)} VIP · ${n(analytics.normal_capacity)} عادية`} icon={Ticket} color="#f59e0b" delay={0.1} />
        <KpiCard title="الضيوف" value={n(analytics.guests_total)} subtitle={`${n(analytics.events_live)} فعالية نشطة`} icon={UserRoundCheck} color="#22c55e" delay={0.15} />
        <KpiCard title="نشاط آخر 30 يوماً" value={n(analytics.activity_30d)} subtitle="عملية موثقة" icon={Activity} color="#ec4899" delay={0.2} />
      </div>

      <div className="plat-detail-tabs" role="tablist" aria-label="أقسام ملف المؤسسة">
        {tabs.map(tab => <button key={tab.key} role="tab" aria-selected={detailTab === tab.key} className={detailTab === tab.key ? 'active' : ''} onClick={() => setDetailTab(tab.key)}>
          {tab.label}{typeof tab.count === 'number' && <span>{n(tab.count)}</span>}
        </button>)}
      </div>

      {detailTab === 'overview' && <div className="plat-detail-grid">
        <div className="plat-panel">
          <div className="plat-panel__head"><CreditCard size={18} /><h3>الاشتراك والاستخدام</h3></div>
          <dl className="plat-facts-grid">
            <div><dt>الباقة</dt><dd>{subscription?.plan_name || tenant.plan}</dd></div>
            <div><dt>الحالة</dt><dd>{subscription?.sub_status || 'لا يوجد اشتراك'}</dd></div>
            <div><dt>السعر الشهري</dt><dd>{subscription ? currency(subscription.price_monthly) : '—'}</dd></div>
            <div><dt>نهاية الفترة</dt><dd>{dateTime(subscription?.current_period_end)}</dd></div>
            <div><dt>فعاليات قيد التخطيط</dt><dd>{n(analytics.events_draft)}</dd></div>
            <div><dt>أدوار مخصصة</dt><dd>{n(roles.length)}</dd></div>
          </dl>
        </div>
        <div className="plat-panel">
          <div className="plat-panel__head"><Settings2 size={18} /><h3>{workspaceGroup.is_linked ? 'هيكل المؤسسة الموحّد' : 'بيانات مساحة العمل'}</h3></div>
          <dl className="plat-facts-grid">
            <div><dt>نوع المساحة</dt><dd>{workspaceGroup.is_linked ? 'فريق تشغيل ومؤسسة فعاليات' : tenant.workspace_type === 'organizer' ? 'فريق تنظيم' : 'مؤسسة'}</dd></div>
            {workspaceGroup.is_linked && <div><dt>مساحة الفعاليات المرتبطة</dt><dd>{workspaceGroup.institution_name || '—'}</dd></div>}
            <div><dt>المعرّف</dt><dd className="plat-mono">{tenant.slug}</dd></div>
            <div><dt>آخر تحديث</dt><dd>{dateTime(tenant.updated_at)}</dd></div>
            <div><dt>تاريخ الانتهاء</dt><dd>{dateTime(tenant.expires_at)}</dd></div>
          </dl>
        </div>
        <div className="plat-panel plat-panel--wide">
          <div className="plat-panel__head"><Calendar size={18} /><h3>آخر الفعاليات</h3></div>
          {recentEvents.length ? <table className="plat-table"><thead><tr><th>الفعالية</th><th>الموعد</th><th>الموقع</th><th>الدعوات</th><th>الحالة</th></tr></thead><tbody>
            {recentEvents.map(event => <tr key={event.id}><td><strong>{event.title}</strong></td><td className="plat-date">{dateTime(event.start_date)}</td><td>{event.location || '—'}</td><td>{n(event.invitations_count)}</td><td><StatusBadge status={event.status} /></td></tr>)}
          </tbody></table> : <div className="plat-empty">لا توجد فعاليات مسجلة لهذه المؤسسة بعد.</div>}
        </div>
      </div>}

      {detailTab === 'members' && <div className="plat-panel">
        <div className="plat-panel__head"><Users size={18} /><h3>أعضاء المؤسسة وصلاحياتهم</h3><span className="plat-muted">إدارة العضوية من داخل المؤسسة؛ هذه شاشة رقابة لمنصة الإدارة.</span></div>
        <table className="plat-table plat-table--full"><thead><tr><th>العضو</th><th>الدور التشغيلي</th><th>الأدوار الممنوحة</th><th>الحالة</th><th>تاريخ الانضمام</th></tr></thead><tbody>
          {members.map(member => <tr key={member.user_id}><td className="plat-user-cell"><div className="plat-avatar">{member.avatar_url ? <img src={member.avatar_url} alt="" /> : <span>{(member.full_name || '?')[0]}</span>}</div><strong>{member.full_name || 'بدون اسم'}</strong></td><td>{member.role}</td><td>{member.assigned_roles.length ? <div className="plat-role-tags">{member.assigned_roles.map(role => <span key={role}>{role}</span>)}</div> : '—'}</td><td><StatusBadge status={member.status} /></td><td className="plat-date">{dateTime(member.created_at)}</td></tr>)}
          {!members.length && <tr><td colSpan={5}><div className="plat-empty">لا يوجد أعضاء مسجلون.</div></td></tr>}
        </tbody></table>
      </div>}

      {detailTab === 'roles' && <div className="plat-panel">
        <div className="plat-panel__head"><Shield size={18} /><h3>الأدوار والصلاحيات</h3><span className="plat-muted">قراءة مركزية للصلاحيات، وتحريرها متاح من تبويب الأدوار.</span></div>
        <table className="plat-table plat-table--full"><thead><tr><th>الدور</th><th>النوع</th><th>الأعضاء</th><th>الصلاحيات</th><th>الوصف</th></tr></thead><tbody>
          {roles.map(role => <tr key={role.id}><td><strong>{role.name}</strong></td><td>{role.is_system_role ? <span className="plat-plan-tag">نظامي</span> : <span className="plat-badge">مخصص</span>}</td><td>{n(role.members_count)}</td><td>{role.permissions?.length ? <span className="plat-permission-count">{n(role.permissions.length)} صلاحية</span> : '—'}</td><td>{role.description || '—'}</td></tr>)}
          {!roles.length && <tr><td colSpan={5}><div className="plat-empty">لا توجد أدوار مخصصة لهذه المؤسسة.</div></td></tr>}
        </tbody></table>
      </div>}

      {detailTab === 'activity' && <div className="plat-panel">
        <div className="plat-panel__head"><Activity size={18} /><h3>سجل النشاط الأخير</h3><span className="plat-muted">آخر 12 عملية موثقة للمؤسسة.</span></div>
        <table className="plat-table plat-table--full"><thead><tr><th>الإجراء</th><th>المنفذ</th><th>المورد</th><th>الوقت</th><th></th></tr></thead><tbody>
          {recentActivity.map(log => <tr key={log.id}><td><span className="plat-action-tag">{log.action}</span></td><td>{log.actor_name || 'النظام'}</td><td className="plat-mono">{[log.resource_type, log.resource_id].filter(Boolean).join(' · ') || '—'}</td><td className="plat-date">{dateTime(log.created_at)}</td><td><ChevronLeft size={16} className="plat-muted" /></td></tr>)}
          {!recentActivity.length && <tr><td colSpan={5}><div className="plat-empty">لا توجد عمليات موثقة حتى الآن.</div></td></tr>}
        </tbody></table>
      </div>}
    </section>
  )
}

function TenantsTab({ onOpenTenant }: { onOpenTenant: (tenant: PlatformTenant) => void }) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const qc = useQueryClient()

  const { data: tenants = [], isLoading } = useQuery({
    queryKey: ['platform-tenants', search, statusFilter],
    queryFn: () => platformAPI.listTenants({ search: search || undefined, status: statusFilter || undefined, limit: 100 }),
  })

  const suspendMut = useMutation({ mutationFn: platformAPI.suspendTenant, onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-tenants'] }) })
  const activateMut = useMutation({ mutationFn: platformAPI.activateTenant, onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-tenants'] }) })
  const cancelMut = useMutation({ mutationFn: platformAPI.cancelTenant, onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-tenants'] }) })

  return (
    <div className="plat-tab-content">
      <div className="plat-toolbar">
        <div className="plat-search-wrap"><Search size={16} /><input placeholder="بحث بالاسم أو المعرّف..." value={search} onChange={e => setSearch(e.target.value)} /></div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">كل الحالات</option>
          <option value="active">نشط</option>
          <option value="trial">تجريبي</option>
          <option value="suspended">معلّق</option>
          <option value="cancelled">ملغى</option>
        </select>
      </div>
      {isLoading ? <div className="plat-loading">جار التحميل...</div> : (
        <table className="plat-table plat-table--full">
          <thead><tr><th>المؤسسة</th><th>المعرّف</th><th>الباقة</th><th>الحالة</th><th>الأعضاء</th><th>التاريخ</th><th>إجراءات</th></tr></thead>
          <tbody>
            {tenants.map(t => (
              <tr key={t.id} className="plat-clickable-row" onClick={() => onOpenTenant(t)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onOpenTenant(t) }}>
                <td><strong>{t.name}</strong>{t.is_workspace_group && <small className="plat-unified-workspace">مؤسسة موحّدة · فريق تشغيل + فعاليات</small>}</td>
                <td className="plat-mono">{t.slug}</td>
                <td><span className="plat-plan-tag">{t.plan}</span></td>
                <td><StatusBadge status={t.status} /></td>
                <td>{t.members_count}</td>
                <td className="plat-date">{new Date(t.created_at).toLocaleDateString('ar-SA')}</td>
                <td className="plat-actions">
                  <button className="plat-detail-btn" onClick={e => { e.stopPropagation(); onOpenTenant(t) }}><span>التفاصيل</span><ChevronLeft size={15} /></button>
                  {t.status === 'active' && (
                    <button className="plat-act-btn plat-act-btn--warn" onClick={e => { e.stopPropagation(); suspendMut.mutate(t.id) }} title="تعليق"><Ban size={14} /></button>
                  )}
                  {(t.status === 'suspended' || t.status === 'cancelled') && (
                    <button className="plat-act-btn plat-act-btn--ok" onClick={e => { e.stopPropagation(); activateMut.mutate(t.id) }} title="تفعيل"><CheckCircle2 size={14} /></button>
                  )}
                  {t.status !== 'cancelled' && (
                    <button className="plat-act-btn plat-act-btn--danger" onClick={e => { e.stopPropagation(); cancelMut.mutate(t.id) }} title="إلغاء"><XCircle size={14} /></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════
   TAB: USERS
   ══════════════════════════════════════════════════ */
function UsersTab() {
  const currentUserId = useAuthStore(s => s.user?.id)
  const qc = useQueryClient()
  const { data: staff = [] } = useQuery({
    queryKey: ['platform-staff'],
    queryFn: platformAPI.listStaff,
  })
  const grantStaff = useMutation({
    mutationFn: platformAPI.grantStaff,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-staff'] })
    },
  })
  const revokeStaff = useMutation({
    mutationFn: platformAPI.revokeStaff,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platform-staff'] })
    },
  })

  const grant = () => {
    const email = window.prompt('أدخل بريد الحساب المسجل الذي تريد منحه إدارة المنصة')?.trim()
    if (email && window.confirm(`منح ${email} صلاحية مدير المنصة؟`)) grantStaff.mutate(email)
  }
  const revoke = (id: string, email: string) => {
    if (window.confirm(`سحب صلاحية مدير المنصة من ${email}؟`)) revokeStaff.mutate(id)
  }

  return (
    <div className="plat-tab-content">
      <div className="plat-panel">
        <div className="plat-panel__head"><Crown size={18} /><h3>مدراء المنصة</h3><button className="plat-act-btn plat-act-btn--ok" onClick={grant} disabled={grantStaff.isPending} title="إضافة مدير منصة"><UserPlus size={14} /></button></div>
        <table className="plat-table plat-table--full">
          <caption className="plat-table-caption">هذه الصفحة لحسابات إدارة المنصة فقط. أعضاء كل مؤسسة وأدوارهم موجودون داخل ملف المؤسسة.</caption>
          <thead><tr><th>المشرف</th><th>البريد الإلكتروني</th><th>الصلاحية</th><th>الإجراء</th></tr></thead>
          <tbody>
            {staff.map(member => (
              <tr key={member.id}>
                <td className="plat-user-cell">
                  <div className="plat-avatar"><span>{(member.full_name || member.email || '?')[0]}</span></div>
                  <strong>{member.full_name || 'بدون اسم'}</strong>
                </td>
                <td className="plat-mono">{member.email}</td>
                <td><span className="plat-badge plat-badge--staff"><Crown size={12} />مدير منصة</span></td>
                <td>{member.id !== currentUserId && <button className="plat-act-btn plat-act-btn--danger" onClick={() => revoke(member.id, member.email)} disabled={revokeStaff.isPending} title="سحب الإدارة"><XCircle size={14} /></button>}</td>
              </tr>
            ))}
            {!staff.length && <tr><td colSpan={4}><div className="plat-empty">لا توجد حسابات إدارة أخرى.</div></td></tr>}
          </tbody>
        </table>
        <p className="plat-muted" style={{ marginTop: 16 }}>لا يمكن سحب صلاحية حسابك الحالي أو ترك المنصة بلا مدير.</p>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════
   TAB: PLANS
   ══════════════════════════════════════════════════ */
const LIMIT_LABELS: Record<string, string> = {
  seats_max: 'الحد الأقصى للمستخدمين',
  events_per_month: 'الأحداث شهرياً',
  invitations_per_event: 'الدعوات لكل حدث',
  invitations_per_month: 'الدعوات شهرياً',
  teams_max: 'فرق العمل',
  team_members_per_team: 'أعضاء الفريق',
  designed_templates: 'القوالب المصممة',
  gates_per_event: 'البوابات لكل حدث',
  guests_max: 'سعة الضيوف القصوى',
  registration_forms_max: 'نماذج التسجيل',
  storage_mb: 'مساحة التخزين (MB)',
  messages_per_month: 'الرسائل شهرياً',
  ai_requests_per_month: 'طلبات AI شهرياً',
}

function PlansTab() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['platform-plans'], queryFn: platformAPI.plansOverview })

  /* ── Editor States ── */
  const [editingPlan, setEditingPlan] = useState<PlanOverviewItem | null>(null)
  const [planLimits, setPlanLimits] = useState<{ key: string; value: number; period: string }[]>([])
  const [loadingLimits, setLoadingLimits] = useState(false)
  const [savingPlan, setSavingPlan] = useState(false)

  const [editingAddon, setEditingAddon] = useState<AddonItem | null>(null)
  const [savingAddon, setSavingAddon] = useState(false)

  /* ── Plan Form States ── */
  const [planForm, setPlanForm] = useState({
    name: '',
    subtitle: '',
    description: '',
    price_monthly: 0,
    price_yearly: 0,
    badge_color: '',
    is_popular: false,
    is_active: true,
  })

  /* ── Addon Form States ── */
  const [addonForm, setAddonForm] = useState({
    label_ar: '',
    label_en: '',
    unit_ar: '',
    icon: '',
    price_per_unit: 0,
  })

  /* ── Actions ── */
  const handleEditPlan = async (plan: PlanOverviewItem) => {
    setEditingPlan(plan)
    setPlanForm({
      name: plan.name,
      subtitle: plan.subtitle || '',
      description: plan.description || '',
      price_monthly: plan.price_monthly,
      price_yearly: plan.price_yearly,
      badge_color: plan.badge_color || '#6b7280',
      is_popular: plan.is_popular,
      is_active: plan.is_active,
    })
    setLoadingLimits(true)
    setPlanLimits([])
    try {
      const limits = await platformAPI.getPlanLimits(plan.id)
      setPlanLimits(limits)
    } catch (err) {
      console.error('Failed to get plan limits', err)
    } finally {
      setLoadingLimits(false)
    }
  }

  const handleLimitChange = (key: string, val: number) => {
    setPlanLimits(prev => prev.map(l => l.key === key ? { ...l, value: val } : l))
  }

  const handleSavePlan = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingPlan) return
    setSavingPlan(true)
    try {
      // 1. Update general plan info
      await platformAPI.updatePlan(editingPlan.id, planForm)
      // 2. Update limits
      await platformAPI.updatePlanLimits(editingPlan.id, planLimits)
      
      qc.invalidateQueries({ queryKey: ['platform-plans'] })
      setEditingPlan(null)
      alert('تم تحديث الباقة بنجاح')
    } catch (err) {
      console.error('Failed to save plan details', err)
      alert('فشل في حفظ التعديلات')
    } finally {
      setSavingPlan(false)
    }
  }

  const handleEditAddon = (addon: AddonItem) => {
    setEditingAddon(addon)
    setAddonForm({
      label_ar: addon.label_ar,
      label_en: addon.label_en,
      unit_ar: addon.unit_ar || '',
      icon: addon.icon || '📦',
      price_per_unit: addon.price_per_unit,
    })
  }

  const handleSaveAddon = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingAddon) return
    setSavingAddon(true)
    try {
      await platformAPI.updateAddon(editingAddon.id, addonForm)
      qc.invalidateQueries({ queryKey: ['platform-plans'] })
      setEditingAddon(null)
      alert('تم تحديث سعر الإضافة بنجاح')
    } catch (err) {
      console.error('Failed to save addon details', err)
      alert('فشل في حفظ تعديلات الإضافة')
    } finally {
      setSavingAddon(false)
    }
  }

  if (isLoading) return <div className="plat-loading">جار التحميل...</div>
  if (!data) return null

  return (
    <div className="plat-tab-content">
      {/* Plans grid */}
      <div className="plat-plans-grid">
        {data.plans.map(p => (
          <motion.div key={p.id} className="plat-plan-card" initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.3 }}>
            <div className="plat-plan-card__head" style={{ borderColor: p.badge_color }}>
              <span className="plat-plan-card__badge" style={{ background: p.badge_color }}>{p.name}</span>
              {p.is_popular && <Crown size={14} className="plat-plan-card__pop" />}
            </div>
            <div className="plat-plan-card__price">
              {p.price_monthly > 0 ? <><strong>${cf.format(p.price_monthly)}</strong><span>/شهر (≈ {formatYer(p.price_monthly)} ر.ي)</span></> : <strong>مجاني</strong>}
            </div>
            <div className="plat-plan-card__stats">
              <div><strong>{n(p.active_subscribers)}</strong><span>مشترك نشط</span></div>
              <div><strong>{n(p.total_subscribers)}</strong><span>إجمالي</span></div>
            </div>
            {p.description && <p className="plat-plan-card__desc">{p.description}</p>}
            <div className="plat-plan-card__actions">
              <button className="plat-edit-badge-btn" onClick={() => handleEditPlan(p)}>تعديل المميزات والأسعار</button>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Custom plans info */}
      <div className="plat-panel" style={{ marginTop: 24 }}>
        <div className="plat-panel__head"><Settings2 size={18} /><h3>الباقات المخصصة</h3></div>
        <div className="plat-kpis-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
          <KpiCard title="باقات مخصصة نشطة" value={n(data.custom_plans.active_custom)} icon={Zap} color="#8b5cf6" />
          <KpiCard title="إجمالي الباقات المخصصة" value={n(data.custom_plans.total_custom)} icon={Package} color="#3b82f6" />
        </div>
      </div>

      {/* Addons */}
      <div className="plat-panel" style={{ marginTop: 24 }}>
        <div className="plat-panel__head"><Package size={18} /><h3>أسعار الإضافات</h3></div>
        <table className="plat-table plat-table--full">
          <thead><tr><th></th><th>العنصر</th><th>التصنيف</th><th>السعر/وحدة</th><th>الخطوة</th><th>إجراءات</th></tr></thead>
          <tbody>
            {data.addons.map(a => (
              <tr key={a.id}>
                <td>{a.icon}</td>
                <td>{a.label_ar}</td>
                <td><span className="plat-cat-tag">{a.category}</span></td>
                <td><strong>${a.price_per_unit}</strong></td>
                <td>{a.step > 1 ? `×${a.step}` : '1'}</td>
                <td className="plat-actions">
                  <button className="plat-act-btn plat-act-btn--warn" onClick={() => handleEditAddon(a)} title="تعديل"><Settings2 size={14} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Modal: Edit Plan & Limits ── */}
      {editingPlan && (
        <div className="plat-modal-backdrop">
          <div className="plat-modal">
            <header className="plat-modal__header">
              <h3>تعديل باقة: {editingPlan.name}</h3>
              <button className="plat-modal__close" onClick={() => setEditingPlan(null)}>&times;</button>
            </header>
            <form onSubmit={handleSavePlan} className="plat-modal__body">
              <div className="plat-section-title">بيانات الباقة الأساسية</div>
              
              <div className="plat-form-grid">
                <div className="plat-field">
                  <label className="plat-field__label">اسم الباقة</label>
                  <input className="plat-field__input" value={planForm.name} onChange={e => setPlanForm({...planForm, name: e.target.value})} required />
                </div>
                <div className="plat-field">
                  <label className="plat-field__label">العنوان الفرعي</label>
                  <input className="plat-field__input" value={planForm.subtitle} onChange={e => setPlanForm({...planForm, subtitle: e.target.value})} />
                </div>
              </div>

              <div className="plat-form-grid">
                <div className="plat-field">
                  <label className="plat-field__label">السعر الشهري ($)</label>
                  <input type="number" className="plat-field__input plat-field__input--ltr" value={planForm.price_monthly} onChange={e => setPlanForm({...planForm, price_monthly: parseFloat(e.target.value) || 0})} required />
                </div>
                <div className="plat-field">
                  <label className="plat-field__label">السعر السنوي ($)</label>
                  <input type="number" className="plat-field__input plat-field__input--ltr" value={planForm.price_yearly} onChange={e => setPlanForm({...planForm, price_yearly: parseFloat(e.target.value) || 0})} required />
                </div>
              </div>

              <div className="plat-form-grid">
                <div className="plat-field">
                  <label className="plat-field__label">لون الشارة (HEX)</label>
                  <input className="plat-field__input plat-field__input--ltr" value={planForm.badge_color} onChange={e => setPlanForm({...planForm, badge_color: e.target.value})} required />
                </div>
                <div className="plat-field" style={{ justifyContent: 'center' }}>
                  <label className="plat-field__check">
                    <input type="checkbox" checked={planForm.is_popular} onChange={e => setPlanForm({...planForm, is_popular: e.target.checked})} />
                    <span>تمييز كباقة شعبية (أكثر مبيعاً)</span>
                  </label>
                </div>
              </div>

              <div className="plat-field">
                <label className="plat-field__label">الوصف</label>
                <textarea className="plat-field__input" style={{ minHeight: 60, resize: 'vertical' }} value={planForm.description} onChange={e => setPlanForm({...planForm, description: e.target.value})} />
              </div>

              <div className="plat-section-title">المميزات والحدود البرمجية</div>
              {loadingLimits ? (
                <div className="plat-loading" style={{ padding: 20 }}>جاري تحميل حدود الباقة...</div>
              ) : (
                <div className="plat-limits-list">
                  {planLimits
                    .filter(limit => [
                      'invitations_per_month',
                      'events_per_month',
                      'gates_per_event',
                      'teams_max',
                      'seats_max',
                      'designed_templates'
                    ].includes(limit.key))
                    .sort((a, b) => {
                      const order = [
                        'invitations_per_month',
                        'events_per_month',
                        'gates_per_event',
                        'teams_max',
                        'seats_max',
                        'designed_templates'
                      ];
                      return order.indexOf(a.key) - order.indexOf(b.key);
                    })
                    .map(limit => (
                      <div key={limit.key} className="plat-limit-row">
                        <span>{LIMIT_LABELS[limit.key] || limit.key}</span>
                        <div className="plat-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                          <input
                            type="number"
                            className="plat-field__input plat-field__input--ltr"
                            style={{ width: '100%', padding: '6px 10px' }}
                            value={limit.value}
                            disabled={limit.value === -1}
                            onChange={e => handleLimitChange(limit.key, parseInt(e.target.value) || 0)}
                          />
                        </div>
                        <label className="plat-field__check" style={{ marginTop: 0 }}>
                          <input
                            type="checkbox"
                            checked={limit.value === -1}
                            onChange={e => handleLimitChange(limit.key, e.target.checked ? -1 : 0)}
                          />
                          <span>غير محدود</span>
                        </label>
                      </div>
                    ))}
                </div>
              )}

              <div className="plat-modal__footer" style={{ padding: '16px 0 0', border: 'none', background: 'none' }}>
                <button type="button" className="plat-btn plat-btn--secondary" onClick={() => setEditingPlan(null)}>إلغاء</button>
                <button type="submit" className="plat-btn plat-btn--primary" disabled={savingPlan}>
                  {savingPlan ? 'جاري الحفظ...' : 'حفظ التعديلات'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modal: Edit Addon Price ── */}
      {editingAddon && (
        <div className="plat-modal-backdrop">
          <div className="plat-modal" style={{ maxWidth: 450 }}>
            <header className="plat-modal__header">
              <h3>تعديل الإضافة: {editingAddon.label_ar}</h3>
              <button className="plat-modal__close" onClick={() => setEditingAddon(null)}>&times;</button>
            </header>
            <form onSubmit={handleSaveAddon} className="plat-modal__body">
              <div className="plat-form-grid plat-form-grid--full">
                <div className="plat-field">
                  <label className="plat-field__label">الاسم بالعربية</label>
                  <input className="plat-field__input" value={addonForm.label_ar} onChange={e => setAddonForm({...addonForm, label_ar: e.target.value})} required />
                </div>
                <div className="plat-field">
                  <label className="plat-field__label">الاسم بالإنجليزية</label>
                  <input className="plat-field__input plat-field__input--ltr" value={addonForm.label_en} onChange={e => setAddonForm({...addonForm, label_en: e.target.value})} required />
                </div>
                <div className="plat-field">
                  <label className="plat-field__label">سعر الوحدة الإضافية ($)</label>
                  <input type="number" step="0.01" className="plat-field__input plat-field__input--ltr" value={addonForm.price_per_unit} onChange={e => setAddonForm({...addonForm, price_per_unit: parseFloat(e.target.value) || 0})} required />
                </div>
                <div className="plat-form-grid" style={{ marginBottom: 0 }}>
                  <div className="plat-field">
                    <label className="plat-field__label">وحدة القياس</label>
                    <input className="plat-field__input" value={addonForm.unit_ar} onChange={e => setAddonForm({...addonForm, unit_ar: e.target.value})} required />
                  </div>
                  <div className="plat-field">
                    <label className="plat-field__label">الرمز (Icon)</label>
                    <input className="plat-field__input" value={addonForm.icon} onChange={e => setAddonForm({...addonForm, icon: e.target.value})} required />
                  </div>
                </div>
              </div>

              <div className="plat-modal__footer" style={{ padding: '16px 0 0', border: 'none', background: 'none' }}>
                <button type="button" className="plat-btn plat-btn--secondary" onClick={() => setEditingAddon(null)}>إلغاء</button>
                <button type="submit" className="plat-btn plat-btn--primary" disabled={savingAddon}>
                  {savingAddon ? 'جاري الحفظ...' : 'حفظ التعديلات'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════
   TAB: SUBSCRIPTIONS
   ══════════════════════════════════════════════════ */
/** Default "valid until" shown in the approval form: one period from today. */
function defaultValidUntil(period: string): string {
  const d = new Date()
  d.setDate(d.getDate() + (period === 'yearly' ? 365 : 30))
  return d.toISOString().slice(0, 10)
}

function BillingRequestsQueue() {
  const qc = useQueryClient()
  const { data: subRequests = [], isLoading: loadingSubs } = useQuery({
    queryKey: ['platform-subscription-requests'],
    queryFn: platformAPI.listSubscriptionRequests,
  })
  const { data: customPending = [], isLoading: loadingCustom } = useQuery({
    queryKey: ['platform-custom-plans-pending'],
    queryFn: platformAPI.listPendingCustomPlans,
  })

  const [approving, setApproving] = useState<{ kind: 'subscription' | 'custom'; row: SubscriptionRequest | PendingCustomPlan } | null>(null)
  const [rejecting, setRejecting] = useState<{ kind: 'subscription' | 'custom'; row: SubscriptionRequest | PendingCustomPlan } | null>(null)
  const [paymentRef, setPaymentRef] = useState('')
  const [validUntil, setValidUntil] = useState('')
  const [rejectNote, setRejectNote] = useState('')

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['platform-subscription-requests'] })
    qc.invalidateQueries({ queryKey: ['platform-custom-plans-pending'] })
    qc.invalidateQueries({ queryKey: ['platform-subs'] })
  }

  const approveSub = useMutation({
    mutationFn: ({ id, ref, until }: { id: string; ref: string; until: string }) =>
      platformAPI.approveSubscriptionRequest(id, ref, until),
    onSuccess: () => { invalidate(); setApproving(null) },
  })
  const rejectSub = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => platformAPI.rejectSubscriptionRequest(id, note),
    onSuccess: () => { invalidate(); setRejecting(null) },
  })
  const activateCustom = useMutation({
    mutationFn: ({ id, ref, until }: { id: string; ref: string; until: string }) =>
      platformAPI.activateCustomPlan(id, ref, until),
    onSuccess: () => { invalidate(); setApproving(null) },
  })
  const rejectCustom = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => platformAPI.rejectCustomPlan(id, note),
    onSuccess: () => { invalidate(); setRejecting(null) },
  })

  const openApprove = (kind: 'subscription' | 'custom', row: SubscriptionRequest | PendingCustomPlan) => {
    setApproving({ kind, row })
    setPaymentRef('')
    const period = kind === 'subscription' ? (row as SubscriptionRequest).metadata.period : (row as PendingCustomPlan).requested_period || 'monthly'
    // For a renewal of the running plan the server suggests current end + one period.
    const suggested = kind === 'subscription' ? (row as SubscriptionRequest).suggested_valid_until : null
    setValidUntil(suggested ? suggested.slice(0, 10) : defaultValidUntil(period))
  }
  const openReject = (kind: 'subscription' | 'custom', row: SubscriptionRequest | PendingCustomPlan) => {
    setRejecting({ kind, row })
    setRejectNote('')
  }
  const confirmApprove = () => {
    if (!approving || !paymentRef.trim() || !validUntil) return
    const untilIso = new Date(validUntil).toISOString()
    if (approving.kind === 'subscription') approveSub.mutate({ id: approving.row.id, ref: paymentRef.trim(), until: untilIso })
    else activateCustom.mutate({ id: approving.row.id, ref: paymentRef.trim(), until: untilIso })
  }
  const confirmReject = () => {
    if (!rejecting || !rejectNote.trim()) return
    if (rejecting.kind === 'subscription') rejectSub.mutate({ id: rejecting.row.id, note: rejectNote.trim() })
    else rejectCustom.mutate({ id: rejecting.row.id, note: rejectNote.trim() })
  }
  const approveBusy = approveSub.isPending || activateCustom.isPending
  const rejectBusy = rejectSub.isPending || rejectCustom.isPending

  const empty = !loadingSubs && !loadingCustom && subRequests.length === 0 && customPending.length === 0

  return (
    <div className="plat-billing-queue">
      <h3 className="plat-section-title">طلبات قيد المراجعة <small>({subRequests.length + customPending.length})</small></h3>
      {(loadingSubs || loadingCustom) ? <div className="plat-loading">جار التحميل...</div> : empty ? (
        <div className="plat-empty">لا توجد طلبات باقات معلّقة حالياً.</div>
      ) : (
        <table className="plat-table plat-table--full">
          <thead><tr><th>المؤسسة</th><th>النوع</th><th>الباقة</th><th>السعر</th><th>الدورة</th><th>ملاحظة مقدم الطلب</th><th>التاريخ</th><th></th></tr></thead>
          <tbody>
            {subRequests.map(r => (
              <tr key={`sub-${r.id}`}>
                <td><strong>{r.tenant_name}</strong><br /><small className="plat-mono">{r.tenant_slug}</small></td>
                <td><span className="plat-plan-tag">{r.is_renewal ? `تجديد (متبقٍ ${r.days_left ?? 0} يوم)` : 'باقة قياسية'}</span></td>
                <td>{r.plan_name}</td>
                <td>{currencyWithYer(r.metadata.period === 'yearly' ? r.price_yearly : r.price_monthly)}</td>
                <td>{r.metadata.period === 'yearly' ? 'سنوي' : 'شهري'}</td>
                <td>{r.metadata.notes || '—'}</td>
                <td className="plat-date">{dateTime(r.created_at)}</td>
                <td className="plat-row-actions">
                  <button className="plat-request-decision plat-request-decision--approve" onClick={() => openApprove('subscription', r)}><CheckCircle2 size={15} />تفعيل</button>
                  <button className="plat-request-decision plat-request-decision--reject" onClick={() => openReject('subscription', r)}><XCircle size={15} />رفض</button>
                </td>
              </tr>
            ))}
            {customPending.map(r => (
              <tr key={`custom-${r.id}`}>
                <td><strong>{r.tenant_name}</strong><br /><small className="plat-mono">{r.tenant_slug}</small></td>
                <td><span className="plat-plan-tag">باقة مخصصة</span></td>
                <td>{r.name}</td>
                <td>{currencyWithYer(r.requested_period === 'yearly' ? r.total_price_yearly : r.total_price_monthly)}</td>
                <td>{r.requested_period === 'yearly' ? 'سنوي' : 'شهري'}</td>
                <td>{r.request_notes || '—'}</td>
                <td className="plat-date">{dateTime(r.created_at)}</td>
                <td className="plat-row-actions">
                  <button className="plat-request-decision plat-request-decision--approve" onClick={() => openApprove('custom', r)}><CheckCircle2 size={15} />تفعيل</button>
                  <button className="plat-request-decision plat-request-decision--reject" onClick={() => openReject('custom', r)}><XCircle size={15} />رفض</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {approving && <div className="plat-modal-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget && !approveBusy) setApproving(null) }}>
        <section className="plat-modal" role="dialog" aria-modal="true">
          <header className="plat-modal__header"><h3>تفعيل الباقة بعد التحقق من الدفع</h3></header>
          <div className="plat-modal__body">
            <label className="plat-review-note">مرجع الدفع <small>رقم الحوالة أو إيصال الاستلام</small>
              <input className="plat-review-note__input" value={paymentRef} onChange={e => setPaymentRef(e.target.value)} placeholder="مثال: حوالة بنكية رقم 12345" />
            </label>
            <label className="plat-review-note">صالحة حتى
              <input className="plat-review-note__input" type="date" value={validUntil} onChange={e => setValidUntil(e.target.value)} />
            </label>
          </div>
          <footer className="plat-modal__footer">
            <button className="plat-btn--secondary" onClick={() => setApproving(null)} disabled={approveBusy}>إلغاء</button>
            <button className="plat-request-decision plat-request-decision--approve" onClick={confirmApprove} disabled={approveBusy || !paymentRef.trim() || !validUntil}>
              <CheckCircle2 size={17} />تأكيد التفعيل
            </button>
          </footer>
        </section>
      </div>}

      {rejecting && <div className="plat-modal-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget && !rejectBusy) setRejecting(null) }}>
        <section className="plat-modal" role="dialog" aria-modal="true">
          <header className="plat-modal__header"><h3>رفض الطلب</h3></header>
          <div className="plat-modal__body">
            <label className="plat-review-note">السبب <small>مطلوب — سيصل للمؤسسة</small>
              <textarea value={rejectNote} onChange={e => setRejectNote(e.target.value)} placeholder="اكتب سبب الرفض..." />
            </label>
          </div>
          <footer className="plat-modal__footer">
            <button className="plat-btn--secondary" onClick={() => setRejecting(null)} disabled={rejectBusy}>إلغاء</button>
            <button className="plat-request-decision plat-request-decision--reject" onClick={confirmReject} disabled={rejectBusy || !rejectNote.trim()}>
              <XCircle size={17} />تأكيد الرفض
            </button>
          </footer>
        </section>
      </div>}
    </div>
  )
}

function SubscriptionsTab() {
  const [planFilter, setPlanFilter] = useState('')
  const { data: subs = [], isLoading } = useQuery({
    queryKey: ['platform-subs', planFilter],
    queryFn: () => platformAPI.listSubscriptions({ plan_code: planFilter || undefined, limit: 100 }),
  })

  return (
    <div className="plat-tab-content">
      <BillingRequestsQueue />

      <h3 className="plat-section-title">كل الاشتراكات</h3>
      <div className="plat-toolbar">
        <select value={planFilter} onChange={e => setPlanFilter(e.target.value)}>
          <option value="">كل الباقات</option>
          <option value="starter">Starter</option>
          <option value="basic">Basic</option>
          <option value="pro">Pro</option>
          <option value="business">Business</option>
          <option value="enterprise">Enterprise</option>
        </select>
      </div>
      {isLoading ? <div className="plat-loading">جار التحميل...</div> : (
        <table className="plat-table plat-table--full">
          <thead><tr><th>المؤسسة</th><th>الباقة</th><th>السعر</th><th>الحالة</th><th>نهاية الفترة</th><th>التاريخ</th></tr></thead>
          <tbody>
            {subs.map(s => (
              <tr key={s.id}>
                <td><strong>{s.tenant_name}</strong><br /><small className="plat-mono">{s.tenant_slug}</small></td>
                <td><span className="plat-plan-tag">{s.plan_name}</span></td>
                <td>{s.price_monthly > 0 ? currency(s.price_monthly) : 'مجاني'}</td>
                <td><StatusBadge status={s.sub_status} /></td>
                <td className="plat-date">{s.current_period_end ? new Date(s.current_period_end).toLocaleDateString('ar-SA') : '—'}</td>
                <td className="plat-date">{new Date(s.created_at).toLocaleDateString('ar-SA')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════
   TAB: AUDIT
   ══════════════════════════════════════════════════ */
function AuditTab() {
  const [actionFilter, setActionFilter] = useState('')
  const { data: logs = [], isLoading } = useQuery({
    queryKey: ['platform-audit', actionFilter],
    queryFn: () => platformAPI.listAuditLogs({ action: actionFilter || undefined, limit: 100 }),
  })

  return (
    <div className="plat-tab-content">
      <div className="plat-toolbar">
        <div className="plat-search-wrap"><Search size={16} /><input placeholder="بحث بالإجراء..." value={actionFilter} onChange={e => setActionFilter(e.target.value)} /></div>
      </div>
      {isLoading ? <div className="plat-loading">جار التحميل...</div> : (
        <table className="plat-table plat-table--full">
          <thead><tr><th>الإجراء</th><th>المنفذ</th><th>المؤسسة</th><th>النوع</th><th>IP</th><th>التاريخ</th></tr></thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id}>
                <td><span className="plat-action-tag">{l.action}</span></td>
                <td>{l.actor_name || '—'}</td>
                <td>{l.tenant_name || '—'}</td>
                <td className="plat-mono">{l.resource_type}</td>
                <td className="plat-mono">{l.ip_address || '—'}</td>
                <td className="plat-date">{new Date(l.created_at).toLocaleDateString('ar-SA', { hour: '2-digit', minute: '2-digit' })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function TeamRequestsTab() {
  const qc = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('pending')
  const [selectedRequest, setSelectedRequest] = useState<OrgRequest | null>(null)
  const [reviewNote, setReviewNote] = useState('')
  const { data: requests = [], isLoading } = useQuery({
    queryKey: ['platform-org-requests', statusFilter],
    queryFn: () => platformAPI.listOrgRequests(statusFilter),
  })
  const approve = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => platformAPI.approveOrgRequest(id, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-org-requests'] }),
  })
  const reject = useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) => platformAPI.rejectOrgRequest(id, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['platform-org-requests'] }),
  })
  const openRequest = (request: OrgRequest) => {
    setSelectedRequest(request)
    setReviewNote(request.review_note || '')
  }
  const closeRequest = () => {
    if (!approve.isPending && !reject.isPending) setSelectedRequest(null)
  }
  const approveRequest = () => {
    if (!selectedRequest) return
    approve.mutate({ id: selectedRequest.id, note: reviewNote.trim() || undefined }, { onSuccess: () => setSelectedRequest(null) })
  }
  const rejectRequest = () => {
    if (!selectedRequest || !reviewNote.trim()) return
    reject.mutate({ id: selectedRequest.id, note: reviewNote.trim() }, { onSuccess: () => setSelectedRequest(null) })
  }

  return <div className="plat-tab-content">
    <div className="plat-toolbar">
      <div className="plat-filters">
        {['pending', 'approved', 'rejected'].map(value => <button key={value} className={statusFilter === value ? 'active' : ''} onClick={() => setStatusFilter(value)}>
          {{ pending: 'قيد المراجعة', approved: 'مقبولة', rejected: 'مرفوضة' }[value]}
        </button>)}
      </div>
    </div>
    {isLoading ? <div className="plat-loading">جار تحميل الطلبات...</div> : <table className="plat-table plat-table--full plat-request-table">
      <thead><tr><th>المؤسسة / الفريق</th><th>مقدم الطلب</th><th>الموقع</th><th>الطلب المتوقع</th><th>الباقة</th><th>التاريخ</th><th>الحالة</th><th></th></tr></thead>
      <tbody>
        {requests.map(req => <tr key={req.id} className="plat-clickable-row" onClick={() => openRequest(req)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') openRequest(req) }}>
          <td><strong>{req.org_name}</strong><small>{req.org_type || 'فريق تنظيم'}</small></td>
          <td><strong>{req.full_name}</strong><small className="plat-mono">{req.email}</small></td>
          <td>{[req.city, req.country].filter(Boolean).join('، ') || '—'}</td>
          <td><strong>{n(req.expected_events_per_month)}</strong><small>فعالية / شهر · {n(req.expected_attendees)} ضيف</small></td>
          <td><span className="plat-plan-tag">{req.requested_plan_code || 'الافتراضية'}</span></td>
          <td className="plat-date">{dateTime(req.created_at)}</td>
          <td><StatusBadge status={req.status} /></td>
          <td><button className="plat-detail-btn" onClick={e => { e.stopPropagation(); openRequest(req) }}><span>التفاصيل</span><ChevronLeft size={15} /></button></td>
        </tr>)}
        {!requests.length && <tr><td colSpan={8}><div className="plat-empty">لا توجد طلبات في هذه الحالة.</div></td></tr>}
      </tbody>
    </table>}

    {selectedRequest && <div className="plat-modal-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) closeRequest() }}>
      <section className="plat-modal plat-request-modal" role="dialog" aria-modal="true" aria-labelledby="request-detail-title">
        <header className="plat-modal__header"><div><span className="plat-header__kicker">طلب انضمام</span><h3 id="request-detail-title">{selectedRequest.org_name}</h3></div><button className="plat-modal__close" onClick={closeRequest} aria-label="إغلاق"><XCircle size={20} /></button></header>
        <div className="plat-modal__body">
          <div className="plat-request-modal__summary"><StatusBadge status={selectedRequest.status} /><span>{selectedRequest.org_type || 'فريق تنظيم'}</span><span>قُدم {dateTime(selectedRequest.created_at)}</span></div>
          <dl className="plat-facts-grid">
            <div><dt>مقدم الطلب</dt><dd>{selectedRequest.full_name}</dd></div>
            <div><dt>البريد الإلكتروني</dt><dd className="plat-mono">{selectedRequest.email}</dd></div>
            <div><dt>الهاتف</dt><dd>{selectedRequest.phone || '—'}</dd></div>
            <div><dt>الموقع</dt><dd>{[selectedRequest.city, selectedRequest.country].filter(Boolean).join('، ') || '—'}</dd></div>
            <div><dt>الفعاليات شهرياً</dt><dd>{n(selectedRequest.expected_events_per_month)}</dd></div>
            <div><dt>الحضور المتوقع</dt><dd>{n(selectedRequest.expected_attendees)}</dd></div>
            <div><dt>الباقة المطلوبة</dt><dd>{selectedRequest.requested_plan_code || 'الافتراضية'}</dd></div>
            <div><dt>الموقع الإلكتروني</dt><dd>{selectedRequest.website ? <a href={selectedRequest.website} target="_blank" rel="noreferrer">فتح الرابط</a> : '—'}</dd></div>
          </dl>
          {selectedRequest.description && <div className="plat-detail-copy"><strong>وصف النشاط</strong><p>{selectedRequest.description}</p></div>}
          {selectedRequest.notes && <div className="plat-detail-copy"><strong>ملاحظات مقدم الطلب</strong><p>{selectedRequest.notes}</p></div>}
          {(selectedRequest.proof_url || selectedRequest.documents_url) && <div className="plat-request-files">{selectedRequest.proof_url && <a href={selectedRequest.proof_url} target="_blank" rel="noreferrer">ملف الإثبات</a>}{selectedRequest.documents_url && <a href={selectedRequest.documents_url} target="_blank" rel="noreferrer">المستندات المرفقة</a>}</div>}
          {selectedRequest.status === 'pending' ? <label className="plat-review-note">ملاحظة المراجعة <small>مطلوبة عند الرفض</small><textarea value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="اكتب ملاحظة داخلية أو سبب الرفض..." /></label> : selectedRequest.review_note && <div className="plat-detail-copy"><strong>ملاحظة المراجعة</strong><p>{selectedRequest.review_note}</p></div>}
        </div>
        <footer className="plat-modal__footer">
          {selectedRequest.status === 'pending' ? <><button className="plat-request-decision plat-request-decision--reject" onClick={rejectRequest} disabled={reject.isPending || !reviewNote.trim()}><XCircle size={17} />رفض الطلب</button><button className="plat-request-decision plat-request-decision--approve" onClick={approveRequest} disabled={approve.isPending}><CheckCircle2 size={17} />موافقة وتفعيل</button></> : <button className="plat-btn--secondary" onClick={closeRequest}>إغلاق</button>}
        </footer>
      </section>
    </div>}
  </div>
}

/* ══════════════════════════════════════════════════════════════
   ██ PLATFORM ADMIN PAGE
   ══════════════════════════════════════════════════════════════ */

export default function PlatformAdminPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [selectedTenant, setSelectedTenant] = useState<PlatformTenant | null>(null)
  const { theme, toggleTheme } = useAdminTheme()
  const clearAuth = useAuthStore(s => s.clearAuth)
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)

  const handleLogout = () => {
    queryClient.clear()
    clearAuth()
  }

  const { data: analytics, isLoading: analyticsLoading, refetch } = useQuery({
    queryKey: ['platform-analytics'],
    queryFn: platformAPI.analytics,
  })

  return (
    <div className="plat-shell" dir="rtl">
      {/* ── Sidebar ── */}
      <aside className="plat-sidebar">
        <div className="plat-brand">
          <div className="plat-brand__icon"><Shield size={24} /></div>
          <div>
            <strong>Qentry</strong>
            <span>إدارة المنصة</span>
          </div>
        </div>

        <nav className="plat-nav">
          {TABS.map(tab => (
            <button
              key={tab.key}
              className={`plat-nav__item${activeTab === tab.key && !selectedTenant ? ' plat-nav__item--active' : ''}`}
              onClick={() => { setSelectedTenant(null); setActiveTab(tab.key) }}
            >
              <tab.icon size={18} />{tab.label}
            </button>
          ))}
        </nav>

        <div className="plat-sidebar__footer">
          <NavLink to="/dashboard" className="plat-nav__item"><Globe size={18} />لوحة التحكم</NavLink>
          <button className="plat-nav__item plat-nav__item--danger" onClick={handleLogout}><LogOut size={18} />تسجيل الخروج</button>
        </div>
      </aside>

      {/* ── Main Content ── */}
      <main className="plat-main">
        <header className="plat-header">
          <div>
            <span className="plat-header__kicker">إدارة المنصة</span>
            <h1>{selectedTenant ? selectedTenant.name : TABS.find(t => t.key === activeTab)?.label}</h1>
          </div>
          <div className="plat-header__actions">
            <span className="plat-user-badge"><Crown size={14} />{user?.full_name || 'مشرف'}</span>
            <button
              className="plat-refresh-btn plat-theme-toggle"
              type="button"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
              aria-label={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
            >
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button className="plat-refresh-btn" type="button" onClick={() => refetch()} title="تحديث البيانات" aria-label="تحديث البيانات"><RefreshCcw size={16} /></button>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.div
            key={selectedTenant ? `tenant-${selectedTenant.id}` : activeTab}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.25 }}
          >
            {selectedTenant ? <TenantDetailPage tenantId={selectedTenant.id} onBack={() => setSelectedTenant(null)} /> : <>
              {activeTab === 'overview' && (analyticsLoading ? <div className="plat-loading">جار تحميل التحليلات...</div> : analytics ? <OverviewTab data={analytics} /> : null)}
              {activeTab === 'team_requests' && <TeamRequestsTab />}
              {activeTab === 'tenants' && <TenantsTab onOpenTenant={setSelectedTenant} />}
              {activeTab === 'users' && <UsersTab />}
              {activeTab === 'roles' && <PlatformRolesTab />}
              {activeTab === 'plans' && <PlansTab />}
              {activeTab === 'subscriptions' && <SubscriptionsTab />}
              {activeTab === 'audit' && <AuditTab />}
            </>}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
