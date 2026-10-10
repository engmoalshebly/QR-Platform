import { type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays, LayoutDashboard, Settings, Users, UserRoundCog,
  Shield, LogOut, Building2, ChevronDown, Mail, Moon, Sun,
} from 'lucide-react'
import { useAdminTheme } from '@app/theme/ThemeProvider'
import { useAuthStore } from '@features/auth/store/authStore'
import { usePermission } from '@shared/permissions'
import { PERM } from '@shared/permissions'
import { useLoadPermissions } from '@features/permissions/hooks/useLoadPermissions'
import { NotificationCenter } from '@features/notifications/components/NotificationCenter'
import '@features/dashboard/pages/dashboard.css'

function NavItem({ to, icon: Icon, label }: { to: string; icon: typeof LayoutDashboard; label: string }) {
  const location = useLocation()

  const getIsActive = () => {
    if (to.includes('?')) {
      const [path, search] = to.split('?')
      return location.pathname === path && location.search === `?${search}`
    }
    return location.pathname === to
  }

  const isActive = getIsActive()

  return (
    <NavLink
      to={to}
      className={`dash-nav__item${isActive ? ' dash-nav__item--active' : ''}`}
      aria-current={undefined}
    >
      <Icon size={18} />{label}
    </NavLink>
  )
}

function PermNavItem({ permission, to, icon, label }: {
  permission: string
  to: string
  icon: typeof LayoutDashboard
  label: string
}) {
  const allowed = usePermission(permission)
  if (!allowed) return null
  return <NavItem to={to} icon={icon} label={label} />
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

  useLoadPermissions()
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
    <div className={`dashboard-shell${hideSidebar ? ' dashboard-shell--full' : ''}`}>
      {!hideSidebar ? <aside className="dash-sidebar">
        <div className="dash-brand">
          <img src="/logo.png" alt="Qentry" />
          <div>
            <strong>Qentry</strong>
            <span>Event OS</span>
          </div>
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

        <nav className="dash-nav" aria-label="Workspace Navigation">
          {isTeamWorkspace ? <>
            <PermNavItem permission={PERM.TEAM_DASHBOARD_VIEW} to="/teams?tab=analytics" icon={LayoutDashboard} label="الرئيسية" />
            <PermNavItem permission={PERM.TEAM_REQUESTS_VIEW} to="/teams?tab=requests" icon={Mail} label="الطلبات" />
            <PermNavItem permission={PERM.TEAM_OPERATIONS_VIEW} to="/teams?tab=events" icon={CalendarDays} label="الحفلات والمشاريع" />
            <PermNavItem permission={PERM.TEAM_OPERATIONS_VIEW} to="/teams?tab=calendar" icon={CalendarDays} label="تقويم الفريق" />
            <PermNavItem permission={PERM.TEAM_MEMBERS_VIEW} to="/users" icon={UserRoundCog} label="أعضاء الفريق" />
            <PermNavItem permission={PERM.TEAM_MEMBERS_VIEW} to="/teams?tab=groups" icon={Users} label="المجموعات التشغيلية" />
            <PermNavItem permission={PERM.TEAM_SETTINGS_VIEW} to="/settings" icon={Settings} label="إعدادات الفريق" />
          </> : <>
            <PermNavItem permission={PERM.NAV_DASHBOARD} to="/dashboard" icon={LayoutDashboard} label="الرئيسية" />
            {!delegatesUserManagement && (
              <PermNavItem permission={PERM.NAV_USERS} to="/users" icon={UserRoundCog} label="المستخدمون" />
            )}
            <PermNavItem permission={PERM.NAV_EVENTS} to="/events" icon={CalendarDays} label="الأحداث" />
            <PermNavItem permission={PERM.NAV_SETTINGS} to="/settings" icon={Settings} label="الإعدادات" />
          </>}
          {user?.is_staff && (
            <>
              <div style={{ borderTop: '1px solid var(--color-border)', margin: '12px 0' }} />
              <NavItem to="/platform" icon={Shield} label="إدارة المنصة" />
            </>
          )}
        </nav>

        <div className="dash-sidebar__footer">
          <button className="dash-nav__item dash-nav__item--danger" onClick={handleLogout}>
            <LogOut size={18} />
            <span>تسجيل الخروج</span>
          </button>
        </div>
      </aside> : null}

      <main className="dash-main">
        <header className="dash-header">
          <div>
            <span className="dash-kicker">لوحة التشغيل</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div className="dash-header__actions">
            <button
              type="button"
              className="dash-icon-btn dash-theme-toggle"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
              aria-label={theme === 'dark' ? 'تفعيل الوضع الفاتح' : 'تفعيل الوضع الداكن'}
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <NotificationCenter />
            {actions}
          </div>
        </header>

        {children}
      </main>
    </div>
  )
}
