import { WhatsAppSettings } from '@features/whatsapp/WhatsAppSettings'
import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckCircle2, ChevronLeft, CircleUserRound, Gauge, Info, Loader2, Save, UserRound } from 'lucide-react'
import { PERM, useAnyPermission, usePermission } from '@shared/permissions'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { useAuthStore } from '@features/auth/store/authStore'
import { settingsAPI } from '../api/settingsApi'
import './settings.css'

const LIMIT_LABELS: Record<string, string> = {
  events_per_month: 'الفعاليات شهريًا', invitations_per_month: 'الدعوات شهريًا', invitations_per_event: 'الدعوات لكل فعالية',
  gates_per_event: 'البوابات لكل فعالية', teams_max: 'فرق العمل', seats_max: 'مقاعد لوحة التحكم',
  designed_templates: 'القوالب المصممة', guests_max: 'الضيوف', storage_mb: 'التخزين (MB)',
  messages_per_month: 'الرسائل شهريًا', ai_requests_per_month: 'طلبات الذكاء الاصطناعي',
}
type SettingsTab = 'general' | 'profile' | 'subscription' | 'whatsapp'
const formatLimit = (value: number) => value === -1 ? 'غير محدود' : value.toLocaleString('ar-SA')
const formatDate = (value?: string | null) => value ? new Intl.DateTimeFormat('ar-SA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'غير متوفر'

export default function SettingsPage() {
  const location = useLocation()
  const tenantId = useAuthStore(s => s.currentTenantId)
  const routeSection: SettingsTab | null = location.pathname === '/settings/subscription'
    ? 'subscription'
    : location.pathname === '/settings/whatsapp' ? 'whatsapp' : null
  const hasSettingsAccess = useAnyPermission(PERM.NAV_SETTINGS, PERM.ORGANIZER_NAV_SETTINGS)
  const canViewBilling = useAnyPermission(PERM.BILLING_VIEW, PERM.BILLING_MANAGE)
  const canEditSettings = usePermission(PERM.SETTINGS_EDIT)
  const canManageWhatsApp = usePermission(PERM.WHATSAPP_MANAGE)
  const hasAccess = routeSection === 'subscription'
    ? canViewBilling
    : routeSection === 'whatsapp' ? canManageWhatsApp : hasSettingsAccess
  const queryClient = useQueryClient()
  const [settingsTab, setSettingsTab] = useState<'general' | 'profile'>('general')
  const activeTab: SettingsTab = routeSection || settingsTab
  const [tenantName, setTenantName] = useState('')
  const [profileName, setProfileName] = useState('')
  const [profilePhone, setProfilePhone] = useState('')
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const tenantQuery = useQuery({ queryKey: ['settings-tenant', tenantId], queryFn: settingsAPI.getCurrentTenant, enabled: Boolean(tenantId) && hasSettingsAccess && !routeSection })
  const usageQuery = useQuery({ queryKey: ['settings-usage', tenantId], queryFn: settingsAPI.getUsage, enabled: Boolean(tenantId) && routeSection === 'subscription' && canViewBilling })
  const profileQuery = useQuery({ queryKey: ['settings-profile'], queryFn: settingsAPI.getProfile, enabled: hasSettingsAccess && !routeSection })

  useEffect(() => { if (tenantQuery.data) setTenantName(tenantQuery.data.name || '') }, [tenantQuery.data])
  useEffect(() => { if (profileQuery.data) { setProfileName(profileQuery.data.full_name || ''); setProfilePhone(profileQuery.data.phone || '') } }, [profileQuery.data])

  const tenantMutation = useMutation({
    mutationFn: () => settingsAPI.updateTenant({ name: tenantName.trim() }),
    onSuccess: () => { setMsg({ type: 'success', text: 'تم حفظ إعدادات المؤسسة.' }); queryClient.invalidateQueries({ queryKey: ['settings-tenant', tenantId] }) },
    onError: () => setMsg({ type: 'error', text: 'تعذر حفظ إعدادات المؤسسة.' }),
  })
  const profileMutation = useMutation({
    mutationFn: () => settingsAPI.updateProfile({ full_name: profileName.trim(), phone: profilePhone.trim() || null }),
    onSuccess: () => { setMsg({ type: 'success', text: 'تم تحديث ملفك الشخصي بنجاح.' }); queryClient.invalidateQueries({ queryKey: ['settings-profile'] }); queryClient.invalidateQueries({ queryKey: ['auth-me'] }) },
    onError: () => setMsg({ type: 'error', text: 'تعذر تحديث الملف الشخصي. تحقق من البيانات.' }),
  })
  if (!hasAccess) return <Navigate to="/dashboard" replace />
  const pageTitle = routeSection === 'subscription' ? 'الاشتراك والاستخدام' : routeSection === 'whatsapp' ? 'WhatsApp' : 'الإعدادات'
  if (!tenantId) return <WorkspaceShell title={pageTitle} subtitle="إدارة مساحة العمل"><div className="dash-state">يرجى اختيار مؤسسة أولًا</div></WorkspaceShell>

  const tabs: Array<{ id: 'general' | 'profile'; label: string; description: string; icon: typeof Building2 }> = [
    { id: 'general', label: 'الإعدادات العامة', description: 'بيانات المؤسسة ومساحة العمل', icon: Building2 },
    { id: 'profile', label: 'ملفي الشخصي', description: 'بيانات حساب المستخدم الحالي', icon: CircleUserRound },
  ]
  return <WorkspaceShell title={pageTitle} subtitle={routeSection === 'subscription' ? 'الباقة الحالية واستهلاك موارد مساحة العمل.' : routeSection === 'whatsapp' ? 'ربط رقم المؤسسة وإدارة الإرسال عبر WhatsApp.' : 'إدارة حسابك الشخصي وإعدادات المؤسسة من مكان واحد'}>
    <div className={`settings-layout${routeSection ? ' settings-layout--single' : ''}`}>
      {!routeSection && <aside className="settings-sidebar" aria-label="أقسام الإعدادات">
        <div className="settings-profile-mini"><div className="settings-avatar">{(profileQuery.data?.full_name || profileQuery.data?.email || 'م').slice(0, 1).toUpperCase()}</div><div><strong>{profileQuery.data?.full_name || 'المستخدم الحالي'}</strong><span>{profileQuery.data?.email || 'جارٍ تحميل الحساب…'}</span></div></div>
        <nav>{tabs.map(({ id, label, description, icon: Icon }) => <button key={id} type="button" className={activeTab === id ? 'active' : ''} onClick={() => { setSettingsTab(id); setMsg(null) }}><Icon size={18} /><span><strong>{label}</strong><small>{description}</small></span><ChevronLeft size={16} /></button>)}</nav>
      </aside>}
      <main className={`settings-content${routeSection ? ' settings-content--plain' : ''}`}>
        {msg && <div className={`settings-msg settings-msg--${msg.type}`}><CheckCircle2 size={17} />{msg.text}</div>}
        {activeTab === 'general' && <section className="settings-section">
          <header><Building2 size={22} /><div><span>مساحة العمل</span><h2>الإعدادات العامة</h2><p>المعلومات الأساسية التي تظهر لأعضاء المؤسسة وفي صفحات النظام.</p></div></header>
          {tenantQuery.isLoading ? <Loader2 className="spin" /> : <form onSubmit={e => { e.preventDefault(); if (tenantName.trim()) tenantMutation.mutate() }}>
            <div className="settings-field"><label htmlFor="org-name">اسم المؤسسة</label><input id="org-name" value={tenantName} onChange={e => { setTenantName(e.target.value); setMsg(null) }} disabled={!canEditSettings} /></div>
            <div className="settings-fields-row"><div className="settings-field"><label htmlFor="org-slug">معرّف مساحة العمل</label><input id="org-slug" value={tenantQuery.data?.slug || ''} disabled /><small>معرّف نظامي ثابت يُستخدم في الروابط والتكاملات.</small></div><div className="settings-field"><label htmlFor="org-status">حالة المؤسسة</label><input id="org-status" value={tenantQuery.data?.status === 'active' ? 'نشطة' : tenantQuery.data?.status || ''} disabled /></div></div>
            {canEditSettings && <div className="settings-actions"><button className="settings-btn settings-btn--primary" disabled={tenantMutation.isPending || !tenantName.trim()}>{tenantMutation.isPending ? <Loader2 size={16} className="spin" /> : <Save size={16} />}حفظ التغييرات</button></div>}
          </form>}
          <div className="settings-note"><Info size={17} /><div><strong>التبديل بين المؤسسات</strong><p>استخدم محدد مساحة العمل في القائمة الرئيسية. تتحدث البيانات والصلاحيات تلقائيًا بعد التبديل.</p></div></div>
        </section>}
        {activeTab === 'profile' && <section className="settings-section">
          <header><UserRound size={22} /><div><span>الحساب الحالي</span><h2>ملفي الشخصي</h2><p>بياناتك الشخصية مستقلة عن اسم المؤسسة وتظهر للزملاء في سجل النشاط والمهام.</p></div></header>
          {profileQuery.isLoading ? <Loader2 className="spin" /> : <form onSubmit={e => { e.preventDefault(); if (profileName.trim().length >= 2) profileMutation.mutate() }}>
            <div className="settings-profile-hero"><div className="settings-avatar settings-avatar--large">{(profileName || profileQuery.data?.email || 'م').slice(0, 1).toUpperCase()}</div><div><strong>{profileName || 'المستخدم الحالي'}</strong><span>{profileQuery.data?.email}</span><small>الحالة: {profileQuery.data?.status === 'active' ? 'نشط' : profileQuery.data?.status || 'نشط'}</small></div></div>
            <div className="settings-fields-row"><div className="settings-field"><label htmlFor="profile-name">الاسم الكامل</label><input id="profile-name" value={profileName} onChange={e => { setProfileName(e.target.value); setMsg(null) }} placeholder="الاسم الكامل" /></div><div className="settings-field"><label htmlFor="profile-phone">رقم الهاتف</label><input id="profile-phone" value={profilePhone} onChange={e => { setProfilePhone(e.target.value); setMsg(null) }} placeholder="مثال: +967 7XX XXX XXX" dir="ltr" /></div></div>
            <div className="settings-field"><label>البريد الإلكتروني</label><input value={profileQuery.data?.email || ''} disabled dir="ltr" /><small>البريد مرتبط ببيانات تسجيل الدخول ولا يمكن تغييره من هذه الصفحة.</small></div>
            <div className="settings-account-meta"><span>آخر تسجيل دخول<strong>{formatDate(profileQuery.data?.last_login_at)}</strong></span><span>تاريخ إنشاء الحساب<strong>{formatDate(profileQuery.data?.created_at)}</strong></span></div>
            <div className="settings-actions"><button className="settings-btn settings-btn--primary" disabled={profileMutation.isPending || profileName.trim().length < 2}>{profileMutation.isPending ? <Loader2 size={16} className="spin" /> : <Save size={16} />}حفظ الملف الشخصي</button></div>
          </form>}
        </section>}
        {activeTab === 'subscription' && <section className="settings-section sub-page">
          {usageQuery.isLoading ? <Loader2 className="spin" /> : usageQuery.data ? <>
            <div className="sub-summary">
              <div className="sub-summary__plan"><Gauge size={20} /><div><small>الباقة الحالية</small><strong>{usageQuery.data.plan_code}</strong></div></div>
              <div className="sub-summary__item"><small>تجديد الاستخدام الشهري</small><strong>{formatDate(usageQuery.data.resets_at)}</strong></div>
              <div className="sub-summary__item"><small>حدود متجاوزة</small><strong className={usageQuery.data.limits.some(l => l.is_exceeded) ? 'is-danger' : 'is-ok'}>{usageQuery.data.limits.filter(l => LIMIT_LABELS[l.key] && l.is_exceeded).length.toLocaleString('ar-SA')}</strong></div>
            </div>
            <div className="sub-section-title"><h2>استهلاك الموارد</h2><span>مقارنة بحدود الباقة</span></div>
            <div className="sub-usage">{usageQuery.data.limits.filter(l => LIMIT_LABELS[l.key]).map(l => {
              const unlimited = l.limit === -1
              const percent = l.limit > 0 ? Math.min(100, Math.round(l.current_usage / l.limit * 100)) : 0
              const level = l.is_exceeded ? 'danger' : percent >= 80 ? 'warn' : 'ok'
              return <div key={l.key} className={`sub-usage__row sub-usage__row--${level}`}>
                <span className="sub-usage__label">{LIMIT_LABELS[l.key]}</span>
                <span className="sub-usage__bar">{unlimited ? <em>غير محدود</em> : <i><b style={{ width: `${percent}%` }} /></i>}</span>
                <span className="sub-usage__value"><strong>{l.current_usage.toLocaleString('ar-SA')}</strong> / {formatLimit(l.limit)}</span>
                <span className="sub-usage__percent">{unlimited ? '—' : `${percent.toLocaleString('ar-SA')}٪`}</span>
              </div>
            })}</div>
            <details className="sub-notes"><summary><Info size={15} />كيف يُحسب الاستخدام؟</summary><ul>
              <li>الأرقام الشهرية تمثل الاستخدام الناجح؛ أرشفة الفعاليات لا تعيد الرصيد واستعادتها لا تستهلكه مجددًا.</li>
              <li>المقاعد تشمل الأعضاء النشطين والدعوات المعلقة.</li>
              <li>الحدود لكل فعالية تعرض أعلى استخدام في فعالية واحدة، والدعوة الجماعية تحسب سجلًا واحدًا ضمن هذا الحد.</li>
              <li>مواعيد التجديد معروضة حسب توقيت جهازك.</li>
            </ul></details>
          </> : <p>تعذر تحميل بيانات الاستخدام.</p>}
        </section>}
        {activeTab === 'whatsapp' && canManageWhatsApp && <WhatsAppSettings key={tenantId} />}
      </main>
    </div>
  </WorkspaceShell>
}
