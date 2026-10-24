import { restoreSessionFromCookie } from '@services/http/client'
import { authAPI } from './api/authApi'
import { useAuthStore } from './store/authStore'
import type { AuthUser } from './types'

const LAST_TENANT = (userId: string) => `qentry_last_tenant:${userId}`

/**
 * Called once before the app renders.  A tab opened after sign-in (a new tab,
 * a link opened in a new window, a restored browser) has no identity of its
 * own; rebuild it from the session cookie instead of sending the user to the
 * login page.
 */
export async function restoreSession(): Promise<void> {
  const token = await restoreSessionFromCookie()
  if (!token) return
  try {
    const me = await authAPI.me()
    const userId = me.user_id || me.id || ''
    const user: AuthUser = {
      id: userId, email: me.email, full_name: me.full_name ?? null,
      avatar_url: me.avatar_url ?? null, is_staff: Boolean(me.is_staff),
    }
    const tenants = (me.tenants || []).filter(t => ['active', 'trial'].includes(t.tenant_status))
    let preferred: string | null = null
    try { preferred = localStorage.getItem(LAST_TENANT(userId)) } catch { /* optional */ }
    const tenantId = user.is_staff ? undefined : (tenants.find(t => t.tenant_id === preferred) ?? tenants[0])?.tenant_id
    useAuthStore.getState().setAuth(user, tenants, tenantId, [])
  } catch {
    // Leave the tab signed out; the login page still works.
  }
}
