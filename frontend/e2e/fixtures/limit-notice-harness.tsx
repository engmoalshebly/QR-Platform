import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { useAuthStore } from '../../src/features/auth/store/authStore'
import { CreateEventDialog } from '../../src/features/events/components/CreateEventDialog'
import { LimitErrorNotice } from '../../src/components/LimitErrorNotice'

export function setRole(role: string) {
  useAuthStore.setState({ currentTenantId: '11111111-1111-1111-1111-111111111111',
    tenants: [{ tenant_id: '11111111-1111-1111-1111-111111111111', role, plan: 'starter', slug: 'test',
      name: 'Test', tenant_status: 'active', membership_status: 'active', workspace_type: 'institution' }], permissions: new Set() })
}

export function mountEventDraft() {
  setRole('owner')
  const mount = document.createElement('div'); document.body.appendChild(mount)
  document.getElementById('root')?.remove()
  createRoot(mount).render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <CreateEventDialog isOpen onClose={() => {}} />
  </MemoryRouter></QueryClientProvider>)
}

export function mountNotice(detail: unknown) {
  setRole('owner')
  const mount = document.createElement('div'); document.body.appendChild(mount)
  document.getElementById('root')?.remove()
  createRoot(mount).render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <LimitErrorNotice error={{ response: { data: { detail } } }} onRetry={() => { mount.dataset.retried = 'true' }} />
  </MemoryRouter></QueryClientProvider>)
  mount.id = 'notice-harness'
}
