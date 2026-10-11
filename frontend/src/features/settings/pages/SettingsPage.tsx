import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckCircle2, ChevronLeft, CircleUserRound, CreditCard, Gauge, Info, Loader2, Save, ShieldCheck, UserRound } from 'lucide-react'
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
type SettingsTab = 'general' | 'profile' | 'subscription' | 'access'
const formatLimit = (value: number) => value === -1 ? 'غير محدود' : value.toLocaleString('ar-SA')
const formatDate = (value?: string | null) => value ? new Intl.DateTimeFormat('ar-SA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'غير متوفر'

export default function SettingsPage() {
  const tenantId = useAuthStore(s => s.currentTenantId)
  const hasAccess = useAnyPermission(PERM.NAV_SETTINGS, PERM.ORGANIZER_NAV_SETTINGS)
  const canEditSettings = usePermission(PERM.SETTINGS_EDIT)
  const canManageRoles = usePermission(PERM.ROLES_MANAGE)
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [tenantName, setTenantName] = useState('')
  const [profileName, setProfileName] = useState('')
  const [profilePhone, setProfilePhone] = useState('')
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const tenantQuery = useQuery({ queryKey: ['settings-tenant', tenantId], queryFn: settingsAPI.getCurrentTenant, enabled: Boolean(tenantId) && hasAccess })
  const usageQuery = useQuery({ queryKey: ['settings-usage', tenantId], queryFn: settingsAPI.getUsage, enabled: Boolean(tenantId) && hasAccess })
  const profileQuery = useQuery({ queryKey: ['settings-profile'], queryFn: settingsAPI.getProfile, enabled: hasAccess })

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
  if (!tenantId) return <WorkspaceShell title="الإعدادات" subtitle="إدارة حسابك ومساحة العمل"><div className="dash-state">يرجى اختيار مؤسسة أولًا</div></WorkspaceShell>

  const tabs: Array<{ id: SettingsTab; label: string; description: string; icon: typeof Building2; visible?: boolean }> = [
    { id: 'general', label: 'الإعدادات العامة', description: 'بيانات المؤسسة ومساحة العمل', icon: Building2 },
    { id: 'profile', label: 'ملفي الشخصي', description: 'بيانات حساب المستخدم الحالي', icon: CircleUserRound },
    { id: 'subscription', label: 'الاشتراك والاستخدام', description: 'الباقة والحدود المتاحة', icon: CreditCard },
    { id: 'access', label: 'الأدوار والصلاحيات', description: 'حوكمة الوصول للمؤسسة', icon: ShieldCheck, visible: canManageRoles },
  ]
  return <WorkspaceShell title="الإعدادات" subtitle="إدارة حسابك الشخصي وإعدادات المؤسسة من مكان واحد">
    <div className="settings-layout">
      <aside className="settings-sidebar" aria-label="أقسام الإعدادات">
        <div className="settings-profile-mini"><div className="settings-avatar">{(profileQuery.data?.full_name || profileQuery.data?.email || 'م').slice(0, 1).toUpperCase()}</div><div><strong>{profileQuery.data?.full_name || 'المستخدم الحالي'}</strong><span>{profileQuery.data?.email || 'جارٍ تحميل الحساب…'}</span></div></div>
        <nav>{tabs.filter(tab => tab.visible !== false).map(({ id, label, description, icon: Icon }) => <button key={id} type="button" className={activeTab === id ? 'active' : ''} onClick={() => { setActiveTab(id); setMsg(null) }}><Icon size={18} /><span><strong>{label}</strong><small>{description}</small></span><ChevronLeft size={16} /></button>)}</nav>
      </aside>
      <main className="settings-content">
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
        {activeTab === 'subscription' && <section className="settings-section">
          <header><Gauge size={22} /><div><span>الفوترة والموارد</span><h2>الاشتراك والاستخدام</h2><p>راقب استهلاك موارد المؤسسة مقارنة بحدود الباقة الحالية.</p></div></header>
          {usageQuery.isLoading ? <Loader2 className="spin" /> : usageQuery.data ? <><span className="settings-plan-badge">الباقة الحالية: {usageQuery.data.plan_code}</span><p>الأرقام الشهرية تمثل الاستخدام الناجح؛ أرشفة الفعاليات لا تعيد الرصيد واستعادتها لا تستهلكه مجددًا. المقاعد تشمل الأعضاء النشطين والدعوات المعلقة. الحدود لكل فعالية تعرض أعلى استخدام في فعالية واحدة، والدعوة الجماعية تحسب سجلًا واحدًا ضمن هذا الحد.</p><p>يتجدد الاستخدام الشهري: {formatDate(usageQuery.data.resets_at)} حسب توقيت جهازك.</p><div className="settings-usage-list">{usageQuery.data.limits.filter(l => LIMIT_LABELS[l.key]).map(l => { const percent = l.limit > 0 ? Math.min(100, Math.round(l.current_usage / l.limit * 100)) : 0; return <div key={l.key} className={`settings-usage-item${l.is_exceeded ? ' settings-usage-item--exceeded' : ''}`}><div><span>{LIMIT_LABELS[l.key]}</span><strong>{l.current_usage.toLocaleString('ar-SA')} / {formatLimit(l.limit)}</strong></div>{l.limit !== -1 && <i><b style={{ width: `${percent}%` }} /></i>}</div> })}</div></> : <p>تعذر تحميل بيانات الاستخدام.</p>}
        </section>}
        {activeTab === 'access' && canManageRoles && <section className="settings-section"><header><ShieldCheck size={22} /><div><span>الحماية والحوكمة</span><h2>الأدوار والصلاحيات</h2><p>حدد ما يمكن لكل دور مشاهدته أو تنفيذه داخل مساحة العمل.</p></div></header><div className="settings-note"><ShieldCheck size={18} /><div><strong>إدارة مركزية للصلاحيات</strong><p>التغييرات تطبق على أعضاء الدور داخل المؤسسة، ويظل حساب المالك محميًا.</p></div></div><Link className="settings-btn settings-btn--primary" to="/settings/roles">فتح إدارة الأدوار والصلاحيات</Link></section>}
      </main>
    </div>
  </WorkspaceShell>
}
