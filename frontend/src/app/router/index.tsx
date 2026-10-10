import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@features/auth/store/authStore'
import { ErrorBoundary } from '@components/ErrorBoundary'
import { LoadingState } from '@components/UiStates'

const LoginPage          = lazy(() => import('@features/auth/pages/LoginPage'))
const SignupPage         = lazy(() => import('@features/auth/pages/SignupPage'))
const VerifySignupPage   = lazy(() => import('@features/auth/pages/VerifySignupPage'))
const ForgotPasswordPage = lazy(() => import('@features/auth/pages/ForgotPasswordPage'))
const AcceptInvitePage   = lazy(() => import('@features/auth/pages/AcceptInvitePage'))
const DashboardPage      = lazy(() => import('@features/dashboard/pages/DashboardPage'))
const UsersPage          = lazy(() => import('@features/users/pages/UsersPage'))
const BookingHubPage     = lazy(() => import('@features/bookings/pages/BookingHubPage'))
const OperationDetailPage = lazy(() => import('@features/operations/pages/OperationDetailPage'))
const EventsPage         = lazy(() => import('@features/events/pages/EventsPage'))
const EventDetailsPage   = lazy(() => import('@features/events/pages/EventDetailsPage'))
const EventDesignEditorPage = lazy(() => import('@features/events/pages/EventDesignEditorPage'))
const PublicInvitationPage = lazy(() => import('@features/invitations/pages/PublicInvitationPage'))
const PublicRegistrationPage = lazy(() => import('@features/invitations/pages/PublicRegistrationPage'))
const PlatformAdminPage  = lazy(() => import('@features/platform/pages/PlatformAdminPage'))
const SettingsPage       = lazy(() => import('@features/settings/pages/SettingsPage'))
const WorkspaceRolesPage = lazy(() => import('@features/settings/pages/WorkspaceRolesPage'))
const LandingPage        = lazy(() => import('@features/landing/pages/LandingPage'))

const LoadingScreen = () => <div className="app-loading-screen"><LoadingState label="جار تجهيز الصفحة…" /></div>
const page = (element: React.ReactNode) => <ErrorBoundary><>{element}</></ErrorBoundary>

function useAuthHydrated() {
  const [hydrated, setHydrated] = useState(() => useAuthStore.persist.hasHydrated())

  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }

    const unsubscribe = useAuthStore.persist.onFinishHydration(() => {
      setHydrated(true)
    })

    return unsubscribe
  }, [])

  return hydrated
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const hasHydrated = useAuthHydrated()

  if (!hasHydrated) {
    return <LoadingScreen />
  }

  return isAuthenticated ? <>{children}</> : <Navigate to="/auth/login" replace />
}

function StaffRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const user = useAuthStore(s => s.user)
  const hasHydrated = useAuthHydrated()

  if (!hasHydrated) return <LoadingScreen />
  if (!isAuthenticated) return <Navigate to="/auth/login" replace />
  if (!user?.is_staff) return <Navigate to="/dashboard" replace />

  return <>{children}</>
}

function InstitutionRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore(s => s.user)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const currentTenant = tenants.find(tenant => tenant?.tenant_id === currentTenantId)
  if (user?.is_staff) return <Navigate to="/platform" replace />
  if (!currentTenant) return <Navigate to="/auth/login" replace />
  if (currentTenant.workspace_type === 'organizer' || currentTenant.role === 'team_manager') return <Navigate to="/teams" replace />
  return <>{children}</>
}

function TeamWorkspaceRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore(s => s.user)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const currentTenant = tenants.find(tenant => tenant?.tenant_id === currentTenantId)
  if (user?.is_staff) return <Navigate to="/platform" replace />
  if (!currentTenant) return <Navigate to="/auth/login" replace />
  if (currentTenant.workspace_type !== 'organizer' && currentTenant.role !== 'team_manager') return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

function UsersWorkspaceRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore(s => s.user)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const currentTenant = tenants.find(tenant => tenant?.tenant_id === currentTenantId)

  if (user?.is_staff) return <Navigate to="/platform" replace />
  if (!currentTenant) return <Navigate to="/auth/login" replace />

  // Companion institutions never administer staff independently. Their linked
  // organizer workspace is the single source of truth for team membership.
  if (currentTenant.workspace_type === 'institution' && currentTenant.linked_tenant_id) {
    return <Navigate to="/dashboard" replace />
  }

  return <>{children}</>
}

function RootRedirect() {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const user = useAuthStore(s => s.user)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const hasHydrated = useAuthHydrated()

  if (!hasHydrated) {
    return <LoadingScreen />
  }

  // The marketing site now lives inside the app as a first-class page.
  if (!isAuthenticated) {
    return <LandingPage />
  }

  const currentTenant = tenants.find(tenant => tenant?.tenant_id === currentTenantId)
  const target = user?.is_staff ? '/platform' : currentTenant?.workspace_type === 'organizer' || currentTenant?.role === 'team_manager' ? '/teams' : '/dashboard'
  return <Navigate to={target} replace />
}

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingScreen />}>
        {page(<Routes>
          {/* ── Auth Routes ── */}
          <Route path="/auth/login"          element={<LoginPage />} />
          <Route path="/auth/signup"         element={<SignupPage />} />
          <Route path="/auth/verify-signup"  element={<VerifySignupPage />} />
          <Route path="/auth/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/invites/accept/:token" element={<AcceptInvitePage />} />

          {/* ── Public Routes (no auth) ── */}
          <Route path="/i/:token" element={<PublicInvitationPage />} />
          <Route path="/register/:slug" element={<PublicRegistrationPage />} />
          <Route path="/e/:slug" element={<PublicRegistrationPage />} />

          {/* ── Protected Routes ── */}
          <Route path="/dashboard" element={<ProtectedRoute><InstitutionRoute><DashboardPage /></InstitutionRoute></ProtectedRoute>} />
          <Route path="/users"     element={<ProtectedRoute><UsersWorkspaceRoute><UsersPage /></UsersWorkspaceRoute></ProtectedRoute>} />
          <Route path="/teams"     element={<ProtectedRoute><TeamWorkspaceRoute><BookingHubPage /></TeamWorkspaceRoute></ProtectedRoute>} />
          <Route path="/team-events/:operationId" element={<ProtectedRoute><TeamWorkspaceRoute><OperationDetailPage /></TeamWorkspaceRoute></ProtectedRoute>} />
          <Route path="/guests" element={<Navigate to="/events" replace />} />
          <Route path="/invitations" element={<Navigate to="/events" replace />} />
          <Route path="/checkin" element={<Navigate to="/events" replace />} />
          <Route path="/settings"  element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
          <Route path="/settings/roles" element={<ProtectedRoute><WorkspaceRolesPage /></ProtectedRoute>} />
          <Route path="/billing/paypal/execute" element={<Navigate to="/dashboard" replace />} />

          <Route path="/events"    element={<ProtectedRoute><InstitutionRoute><EventsPage /></InstitutionRoute></ProtectedRoute>} />
          <Route path="/events/:eventId" element={<ProtectedRoute><InstitutionRoute><EventDetailsPage /></InstitutionRoute></ProtectedRoute>} />
          <Route path="/events/:eventId/design" element={<ProtectedRoute><InstitutionRoute><EventDesignEditorPage /></InstitutionRoute></ProtectedRoute>} />

          {/* ── Platform Admin (Staff Only) ── */}
          <Route path="/platform" element={<StaffRoute><PlatformAdminPage /></StaffRoute>} />

          {/* ── Fallbacks ── */}
          <Route path="/"  element={<RootRedirect />} />
          <Route path="*"  element={<RootRedirect />} />
        </Routes>)}
      </Suspense>
    </BrowserRouter>
  )
}
