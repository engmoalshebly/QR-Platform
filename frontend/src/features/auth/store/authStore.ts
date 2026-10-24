import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { STORAGE, setAccessToken } from '@services/http/client'
import type { AuthUser, TenantInfo } from '../types'

const rememberTenant = (userId: string | undefined, tenantId: string | null) => {
  if (!userId || !tenantId) return
  try { localStorage.setItem(`qentry_last_tenant:${userId}`, tenantId) } catch { /* optional */ }
}

interface AuthStore {
  user:            AuthUser | null
  tenants:         TenantInfo[]
  currentTenantId: string | null
  permissions:     Set<string>
  isAuthenticated: boolean

  setAuth: (user: AuthUser, tenants: TenantInfo[], tenantId?: string, permissions?: string[]) => void
  setTenant: (tenantId: string) => void
  setPermissions: (permissions: string[]) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set) => ({
      user:            null,
      tenants:         [],
      currentTenantId: null,
      permissions:     new Set<string>(),
      isAuthenticated: false,

      setAuth: (user, tenants, tenantId, permissions) => {
        const tid = tenantId || tenants[0]?.tenant_id || null
        if (tid) sessionStorage.setItem(STORAGE.TENANT_ID, tid)
        else sessionStorage.removeItem(STORAGE.TENANT_ID)
        rememberTenant(user?.id, tid)
        set({
          user,
          tenants,
          currentTenantId: tid,
          permissions: new Set(permissions || []),
          isAuthenticated: true,
        })
      },

      setTenant: (tenantId) => {
        sessionStorage.setItem(STORAGE.TENANT_ID, tenantId)
        rememberTenant(useAuthStore.getState().user?.id, tenantId)
        set({ currentTenantId: tenantId })
      },

      setPermissions: (permissions) => {
        set({ permissions: new Set(permissions) })
      },

      clearAuth: () => {
        Object.values(STORAGE).forEach(k => sessionStorage.removeItem(k))
        setAccessToken(null)
        set({ user: null, tenants: [], currentTenantId: null, permissions: new Set(), isAuthenticated: false })
      },
    }),
    {
      name: 'qentry-auth',
      // Account identity must not be shared by every tab.  Tokens were
      // already session-scoped; persisting this store in sessionStorage keeps
      // the identity, tenant and permissions aligned with that token.
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({
        user:            s.user,
        tenants:         s.tenants,
        currentTenantId: s.currentTenantId,
        permissions:     Array.from(s.permissions),
      }),
      merge: (persisted, current) => {
        // A new browser tab has no persisted session yet. Treat that as an
        // empty state so hydration always finishes and the route can redirect
        // to the login screen instead of remaining on the loading screen.
        const p = (persisted ?? {}) as Partial<AuthStore> & { permissions?: string[] }
        return {
          ...current,
          ...p,
          permissions: new Set(p.permissions || []),
          // The access token is memory-only, so a reload cannot prove a session
          // from storage.  The stored identity lets the first request renew the
          // session from the HttpOnly cookie; if that fails the user is sent to login.
          isAuthenticated: Boolean(p.user),
        }
      },
    }
  )
)
