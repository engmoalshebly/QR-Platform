import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '../../src/app/theme/ThemeProvider'
import { useAuthStore } from '../../src/features/auth/store/authStore'
import { PERM } from '../../src/shared/permissions'
import EventDetailsPage from '../../src/features/events/pages/EventDetailsPage'
import { setAccessToken } from '../../src/services/http/client'

export function mountWorkspaceChrome() {
  useAuthStore.setState({
    isAuthenticated: false,
    user: { id: 'preview-user', full_name: 'محمد الشبلي', email: 'preview@example.com', avatar_url: null, is_staff: false },
    currentTenantId: 'preview-tenant',
    tenants: [{ tenant_id: 'preview-tenant', name: 'مؤسسة آفاق للمناسبات', slug: 'afaq', tenant_status: 'active', plan: 'pro', role: 'owner', membership_status: 'active', workspace_type: 'institution' }],
    permissions: new Set(Object.values(PERM)),
  })
  setAccessToken('preview-token')
  document.getElementById('root')!.style.display = 'none'
  const host = document.createElement('div')
  document.body.append(host)
  window.history.replaceState(null, '', '/events/preview')
  createRoot(host).render(<ThemeProvider><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><BrowserRouter><Routes><Route path="/events/:eventId" element={<EventDetailsPage />} /></Routes></BrowserRouter></QueryClientProvider></ThemeProvider>)
}
