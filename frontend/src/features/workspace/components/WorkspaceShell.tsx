import { BrandLogo } from '@components/BrandLogo'
import { SubscriptionStatusBanner } from './SubscriptionStatusBanner'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, LayoutDashboard, Settings, Users, UserRoundCog,
  Shield, LogOut, Building2, ChevronDown, Mail, Moon, Sun, PanelRightClose, PanelRightOpen,
  CreditCard, MessageCircle, ShieldCheck, Menu, X, ChevronLeft,
} from 'lucide-react'
import { useAdminTheme } from '@app/theme/ThemeProvider'
import { useAuthStore } from '@features/auth/store/authStore'
import { useAnyPermission, usePermission } from '@shared/permissions'
import { PERM } from '@shared/permissions'
import { useLoadPermissions } from '@features/permissions/hooks/useLoadPermissions'
import { NotificationCenter } from '@features/notifications/components/NotificationCenter'
import '@features/dashboard/pages/dashboard.css'
import './workspace-shell.css'

function NavItem({ to, icon: Icon, label, collapsed = false }: { to: string; icon: typeof LayoutDashboard; label: string; collapsed?: boolean }) {
  const location = useLocation()

  const getIsActive = () => {
    if (to.includes('?')) {
      const [path, search] = to.split('?')
      const expected = new URLSearchParams(search).get('tab')
      const actual = new URLSearchParams(location.search).get('tab') || 'analytics'
      return location.pathname === path && actual === expected
    }
    return location.pathname === to
  }

  const isActive = getIsActive()

  return (
    <NavLink
      to={to}
      end
      className={`dash-nav__item${isActive ? ' dash-nav__item--active' : ''}`}
      title={collapsed ? label : undefined}
      aria-current={isActive ? 'page' : false}
    >
      <Icon size={18} /><span className="dash-nav__label">{label}</span>
    </NavLink>
  )
}

function PermNavItem({ permission, to, icon, label, collapsed = false }: {
  permission: string
  to: string
  icon: typeof LayoutDashboard
  label: string
  collapsed?: boolean
}) {
  const allowed = usePermission(permission)
  if (!allowed) return null
  return <NavItem to={to} icon={icon} label={label} collapsed={collapsed} />
}

export function WorkspaceShell({
  title,
  subtitle,
  actions,
  children,
  hideSidebar = false,
}: {
  title: string
  subtitle: string
  actions?: ReactNode
  children: ReactNode
  hideSidebar?: boolean
}) {
  const user = useAuthStore(s => s.user)
  const tenants = useAuthStore(s => s.tenants) || []
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const setTenant = useAuthStore(s => s.setTenant)
  const clearAuth = useAuthStore(s => s.clearAuth)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { theme, toggleTheme } = useAdminTheme()
  const [mobileOpen, setMobileOpen] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!mobileOpen) return
    const menuButton = menuButtonRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const main = mainRef.current
    if (main) main.inert = true
    const focusable = () => Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('a[href], button, select') || []).filter(node => node.getClientRects().length > 0)
    focusable()[0]?.focus()
    const close = () => setMobileOpen(false)
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key !== 'Tab') return
      const items = focusable()
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const desktop = window.matchMedia('(min-width: 901px)')
    desktop.addEventListener('change', close)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      if (main) main.inert = false
      desktop.removeEventListener('change', close)
      document.removeEventListener('keydown', onKeyDown)
      menuButton?.focus()
    }
  }, [mobileOpen])
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('qentry_workspace_sidebar_collapsed') === 'true' } catch { return false }
  })
  const toggleSidebar = () => setSidebarCollapsed(previous => {
    const next = !previous
    try { localStorage.setItem('qentry_workspace_sidebar_collapsed', String(next)) } catch { /* storage may be unavailable */ }
    return next
  })

  useLoadPermissions()
  const canViewBilling = useAnyPermission(PERM.BILLING_VIEW, PERM.BILLING_MANAGE)
  const canManageWhatsApp = usePermission(PERM.WHATSAPP_MANAGE)
  const canManageRoles = usePermission(PERM.ROLES_MANAGE)
  const hasWorkspaceAdminLinks = canViewBilling || canManageWhatsApp || canManageRoles
  const currentTenant = (tenants || []).find(t => t?.tenant_id === currentTenantId)
  const isTeamWorkspace = currentTenant?.workspace_type === 'organizer' || currentTenant?.role === 'team_manager'
  // A companion institution delegates staff administration to its linked
  // organizer workspace. Keep the institution focused on client events.
  const delegatesUserManagement = currentTenant?.workspace_type === 'institution' && Boolean(currentTenant?.linked_tenant_id)

  const handleTenantChange = (tenantId: string) => {
    if (tenantId === currentTenantId) return
    const nextTenant = (tenants || []).find(tenant => tenant?.tenant_id === tenantId)
    setTenant(tenantId)
    queryClient.invalidateQueries()
    navigate(nextTenant?.workspace_type === 'organizer' || nextTenant?.role === 'team_manager' ? '/teams' : '/dashboard')
  }

  const handleLogout = () => {
    queryClient.clear()
    clearAuth()
  }

  return (
    <div className={`dashboard-shell${hideSidebar ? ' dashboard-shell--full' : ''}${mobileOpen ? ' dashboard-shell--menu-open' : ''}`}>
      {mobileOpen && <button type="button" className="dash-mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="إغلاق القائمة الجانبية" tabIndex={-1} />}
      {!hideSidebar ? <aside ref={sidebarRef} id="workspace-navigation" aria-label="القائمة الرئيسية" className={`dash-sidebar${sidebarCollapsed ? ' dash-sidebar--collapsed' : ''}`}>
        <button type="button" className="dash-mobile-close" onClick={() => setMobileOpen(false)} aria-label="إغلاق القائمة"><X size={20} /></button>
        <button type="button" aria-expanded={!sidebarCollapsed} className="dash-sidebar__toggle" onClick={toggleSidebar}
          aria-label={sidebarCollapsed ? 'توسيع القائمة الجانبية' : 'تصغير القائمة الجانبية'}
          title={sidebarCollapsed ? 'توسيع القائمة' : 'تصغير القائمة'}>
          {sidebarCollapsed ? <PanelRightOpen size={17} /> : <PanelRightClose size={17} />}
        </button>
        <div className="dash-brand">
          <NavLink to={isTeamWorkspace ? "/teams" : "/dashboard"} aria-label="دعوة — الرئيسية" onClick={() => setMobileOpen(false)}><span className="dash-brand__full"><BrandLogo /></span><span className="dash-brand__symbol"><BrandLogo symbol /></span></NavLink>
        </div>

        {(tenants?.length ?? 0) > 0 && (
          <div className="dash-tenant-switcher">
            <label className="dash-tenant-switcher__label" htmlFor="tenant-select">
              <Building2 size={14} />
              مساحة العمل
            </label>
            {tenants.length === 1 ? (
              <div className="dash-tenant-switcher__single">{currentTenant?.name || '—'}</div>
            ) : (
              <div className="dash-tenant-switcher__select-wrap">
                <select
                  id="tenant-select"
                  className="dash-tenant-switcher__select"
                  value={currentTenantId || ''}
                  onChange={(e) => handleTenantChange(e.target.value)}
                >
                  {(tenants || []).map(t => (
                    <option key={t.tenant_id} value={t.tenant_id}>{t.name}</option>
                  ))}
                </select>
                <ChevronDown size={14} className="dash-tenant-switcher__icon" />
              </div>
            )}
          </div>
        )}

        <nav className="dash-nav" aria-label="التنقل في مساحة العمل" onClick={event => { if ((event.target as HTMLElement).closest('a')) setMobileOpen(false) }}>
          <span className="dash-nav__section">مساحة العمل</span>
          {isTeamWorkspace ? <>
            <PermNavItem permission={PERM.TEAM_DASHBOARD_VIEW} to="/teams?tab=analytics" icon={LayoutDashboard} label="الرئيسية" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_REQUESTS_VIEW} to="/teams?tab=requests" icon={Mail} label="الطلبات" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_OPERATIONS_VIEW} to="/teams?tab=events" icon={CalendarDays} label="الحفلات والمشاريع" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_OPERATIONS_VIEW} to="/teams?tab=calendar" icon={CalendarDays} label="تقويم الفريق" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_MEMBERS_VIEW} to="/users" icon={UserRoundCog} label="أعضاء الفريق" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_MEMBERS_VIEW} to="/teams?tab=groups" icon={Users} label="مجموعات الفريق" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.TEAM_SETTINGS_VIEW} to="/settings" icon={Settings} label="إعدادات الفريق" collapsed={sidebarCollapsed} />
          </> : <>
            <PermNavItem permission={PERM.NAV_DASHBOARD} to="/dashboard" icon={LayoutDashboard} label="الرئيسية" collapsed={sidebarCollapsed} />
            {!delegatesUserManagement && (
              <PermNavItem permission={PERM.NAV_USERS} to="/users" icon={UserRoundCog} label="أعضاء الفريق" collapsed={sidebarCollapsed} />
            )}
            <PermNavItem permission={PERM.NAV_EVENTS} to="/events" icon={CalendarDays} label="المناسبات" collapsed={sidebarCollapsed} />
            <PermNavItem permission={PERM.NAV_SETTINGS} to="/settings" icon={Settings} label="الإعدادات" collapsed={sidebarCollapsed} />
          </>}
          {hasWorkspaceAdminLinks && <span className="dash-nav__section dash-nav__section--divider">إدارة المؤسسة</span>}
          {canViewBilling && <NavItem to="/settings/subscription" icon={CreditCard} label="الاشتراك والاستخدام" collapsed={sidebarCollapsed} />}
          {canManageWhatsApp && <NavItem to="/settings/whatsapp" icon={MessageCircle} label="WhatsApp" collapsed={sidebarCollapsed} />}
          {canManageRoles && <NavItem to="/settings/roles" icon={ShieldCheck} label="الأدوار والصلاحيات" collapsed={sidebarCollapsed} />}
          {user?.is_staff && (
            <>
              <span className="dash-nav__section dash-nav__section--divider">إدارة النظام</span>
              <NavItem to="/platform" icon={Shield} label="إدارة المنصة" collapsed={sidebarCollapsed} />
            </>
          )}
        </nav>

        <div className="dash-sidebar__footer">
          <div className="dash-account" title={user?.email}>
            <span className="dash-account__avatar" aria-hidden="true">{(user?.full_name || user?.email || 'م').slice(0, 1).toUpperCase()}</span>
            <div className="dash-account__info"><strong>{user?.full_name || 'حسابي'}</strong><small>{user?.email}</small></div>
          </div>
          <button className="dash-nav__item dash-nav__item--danger" onClick={handleLogout} title="تسجيل الخروج">
            <LogOut size={17} /><span className="dash-nav__label">تسجيل الخروج</span>
          </button>
        </div>
      </aside> : null}
      <main className="dash-main" ref={mainRef}>
        <div className="dash-topbar">
          <div className="dash-topbar__context">
            {!hideSidebar && <button ref={menuButtonRef} type="button" className="dash-icon-btn dash-mobile-menu" onClick={() => setMobileOpen(true)} aria-label="فتح القائمة الرئيسية" aria-controls="workspace-navigation" aria-expanded={mobileOpen}><Menu size={20} /></button>}
            <Building2 size={16} aria-hidden="true" /><span className="dash-topbar__tenant">{currentTenant?.name || 'مساحة العمل'}</span>
            <ChevronLeft size={14} className="dash-topbar__separator" aria-hidden="true" /><span className="dash-topbar__page">{title}</span>
          </div>
          <div className="dash-topbar__tools">
            <button type="button" className="dash-icon-btn dash-theme-toggle" onClick={toggleTheme}
              title={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
              aria-label={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}>
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <NotificationCenter />
          </div>
        </div>
        <header className="dash-header">
          <div className="dash-header__title"><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
          {actions && <div className="dash-header__actions">{actions}</div>}
        </header>

        <SubscriptionStatusBanner />
        {children}
      </main>
    </div>
  )
}
