import axios from 'axios'

export { getApiErrorCode, getApiErrorMessage } from './apiErrors'
export type { LimitErrorCode } from './apiErrors'

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'
// The access token lives in memory only: a script that reads storage cannot take
// it.  The refresh token is an HttpOnly cookie that the browser sends on its own.
// Restore the cookie session before sending requests after a reload.
let accessTokenMemory: string | null = null
let proactiveTimer: number | undefined

// ── Session coordination across tabs ──
// Every tab keeps its own access token, but they share one refresh-token
// cookie.  The refresh token rotates on each use, so two tabs refreshing
// independently (or a refresh whose response was lost) used to present an
// already-rotated token, which the identity provider treats as theft and
// answers by ending the whole session.  Refreshes are therefore serialised
// with a cross-tab lock, and the new access token is shared with other tabs.
const SESSION_CHANNEL = 'qentry-session'
const SESSION_HINT = 'qentry_has_session'
const channel: BroadcastChannel | null = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(SESSION_CHANNEL) : null

const tokenExpiry = (token: string | null): number => {
  try {
    const payload = JSON.parse(atob((token || '').split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' ? payload.exp * 1000 : 0
  } catch { return 0 }
}
const isFresh = (token: string | null, marginMs = 60_000) => Boolean(token) && tokenExpiry(token) - Date.now() > marginMs

const scheduleProactiveRefresh = (token: string | null) => {
  window.clearTimeout(proactiveTimer)
  if (!token) return
  // Renew two minutes before expiry so requests never meet an expired token.
  const delay = Math.max(5_000, tokenExpiry(token) - Date.now() - 120_000)
  proactiveTimer = window.setTimeout(() => {
    if (document.visibilityState === 'visible' || !isFresh(accessTokenMemory, 30_000)) void renewSession().catch(() => undefined)
  }, delay)
}

export const setAccessToken = (token: string | null) => {
  accessTokenMemory = token
  scheduleProactiveRefresh(token)
  try {
    if (token) localStorage.setItem(SESSION_HINT, '1')
  } catch { /* storage may be unavailable */ }
}

/** Forget the session in this tab and tell the other tabs to do the same. */
export const endSessionEverywhere = () => {
  accessTokenMemory = null
  window.clearTimeout(proactiveTimer)
  try { localStorage.removeItem(SESSION_HINT) } catch { /* optional */ }
  channel?.postMessage({ type: 'logout' })
}

const forgetLocalIdentity = () => {
  Object.values(STORAGE).forEach(key => sessionStorage.removeItem(key))
  sessionStorage.removeItem('qentry-auth')
}

channel?.addEventListener('message', ({ data }) => {
  if (data?.type === 'token' && typeof data.token === 'string') {
    accessTokenMemory = data.token
    scheduleProactiveRefresh(data.token)
  } else if (data?.type === 'logout' && hasStoredIdentity()) {
    accessTokenMemory = null
    forgetLocalIdentity()
    window.location.assign('/auth/login')
  }
})

/** Whether this browser signed in before (cheap hint; the cookie decides). */
export const hasSessionHint = () => {
  try { return localStorage.getItem(SESSION_HINT) === '1' } catch { return false }
}

// Header that a cross-site form cannot send.  The server requires it before it
// rotates a session from the cookie.
const CSRF_HEADERS = { 'X-Requested-With': 'qentry' } as const

const sleep = (ms: number) => new Promise(resolve => window.setTimeout(resolve, ms))

const requestRefresh = async (): Promise<string> => {
  // Retries stay inside the provider's reuse window, so a refresh whose
  // response was lost is repeated with the same cookie instead of later.
  const delays = [0, 700, 2_000, 4_000]
  let lastError: unknown
  for (const delay of delays) {
    if (delay) await sleep(delay)
    try {
      const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {}, {
        withCredentials: true,
        timeout: 15_000,
        headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS },
      })
      if (typeof data.access_token !== 'string' || !data.access_token) throw new Error('Missing access token in refresh response')
      return data.access_token as string
    } catch (error) {
      lastError = error
      const status = (error as { response?: { status?: number } }).response?.status
      if (status === 401 || status === 403) throw error // the session is really gone
    }
  }
  throw lastError
}

const withRefreshLock = <T,>(task: () => Promise<T>): Promise<T> => {
  // Web Locks are supported by every current browser; without them each tab
  // still refreshes on its own, as before.
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined
  return locks ? (locks.request('qentry-session-refresh', task) as Promise<T>) : task()
}

let refreshPromise: Promise<string> | null = null
const renewSession = (): Promise<string> => {
  if (!refreshPromise) {
    const tokenBefore = accessTokenMemory
    refreshPromise = withRefreshLock(async () => {
      // Another tab may have refreshed while this one waited for the lock.
      if (accessTokenMemory && accessTokenMemory !== tokenBefore && isFresh(accessTokenMemory)) return accessTokenMemory
      const token = await requestRefresh()
      setAccessToken(token)
      channel?.postMessage({ type: 'token', token })
      return token
    }).catch(error => {
      const status = error?.response?.status
      if (status === 401 || status === 403) {
        forgetLocalIdentity()
        endSessionEverywhere()
        window.location.assign('/auth/login')
      }
      throw error
    }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

/**
 * A new tab has no identity in sessionStorage.  If this browser holds a valid
 * session cookie, restore the session instead of asking for the password again.
 */
export const restoreSessionFromCookie = async (): Promise<string | null> => {
  if (hasStoredIdentity() || !hasSessionHint()) return null
  try {
    return await withRefreshLock(async () => {
      const token = await requestRefresh()
      setAccessToken(token)
      channel?.postMessage({ type: 'token', token })
      return token
    })
  } catch (error) {
    const status = (error as { response?: { status?: number } }).response?.status
    if (status === 401 || status === 403) {
      try { localStorage.removeItem(SESSION_HINT) } catch { /* optional */ }
    }
    return null
  }
}

const hasStoredIdentity = () => {
  try { return Boolean(JSON.parse(sessionStorage.getItem('qentry-auth') || '{}').state?.user) }
  catch { return false }
}

/** Download a protected file without exposing the access token in a URL. */
export const downloadAuthenticatedFile = async (url: string, fallbackName = 'download') => {
  const target = new URL(url, window.location.origin)
  if (target.origin !== window.location.origin && /\/storage\/v1\/object\/(sign|public)\/invitations\/.+\.(pdf|zip)$/i.test(target.pathname)) {
    const refreshed = await http.post<{ download_url: string }>('/fast-invitations/refresh-download', { reference: url })
    url = refreshed.data.download_url
    if (new URL(url).origin !== target.origin) throw new Error('تعذر التحقق من وجهة التنزيل')
  }
  // Signed/public storage URLs authorize themselves. Never forward the
  // platform JWT, tenant header or cookies to a different origin.
  const response = target.origin === window.location.origin
    ? await http.get(url, { responseType: 'blob' })
    : await axios.get(url, { responseType: 'blob', withCredentials: false, timeout: 120_000 })
  const disposition = String(response.headers['content-disposition'] || '')
  const matchedName = /filename\*?=(?:UTF-8''|")?([^;"]+)/i.exec(disposition)?.[1]
  const filename = matchedName ? decodeURIComponent(matchedName.replace(/["']/g, '')) : fallbackName
  const blobUrl = URL.createObjectURL(new Blob([response.data]))
  const anchor = document.createElement('a')
  anchor.href = blobUrl
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(blobUrl)
}

// ── Storage Keys ──
export const STORAGE = {
  TENANT_ID:     'qentry_tenant_id',
  USER:          'qentry_user',
  TENANTS:       'qentry_tenants',
} as const

// ── Axios Instance ──
export const http = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000,
  withCredentials: true,
})

// ── Request Interceptor: attach token + tenant ──
http.interceptors.request.use(async (config) => {
  const isSessionEndpoint = /\/auth\/(login|refresh|logout)(?:[/?]|$)/.test(config.url || '')
  if (!accessTokenMemory && !isSessionEndpoint && hasStoredIdentity()) {
    await renewSession()
  }
  const token = accessTokenMemory
  // Tenant context is deliberately scoped to the browser tab.  Keeping it in
  // localStorage let one account overwrite another account's active tenant
  // when both were open in separate tabs of the same browser.
  const tenantId = sessionStorage.getItem(STORAGE.TENANT_ID)

  if (tenantId === 'undefined' || tenantId === 'null') {
    sessionStorage.removeItem(STORAGE.TENANT_ID)
  }

  if (token) config.headers.Authorization = `Bearer ${token}`
  const validTenantId = sessionStorage.getItem(STORAGE.TENANT_ID)
  if (validTenantId && validTenantId !== 'undefined' && validTenantId !== 'null') {
    config.headers['X-Tenant-ID'] = validTenantId
  }

  return config
})

// ── Response Interceptor: auto refresh on 401 ──
http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config as typeof error.config & { _retry?: boolean }

    const isAuthRoute = original?.url?.includes('/auth/login') ||
                        original?.url?.includes('/auth/refresh')

    if (error.response?.status === 401 && original && !original._retry && !isAuthRoute) {
      original._retry = true
      try {
        // A slower request may fail after another request already renewed.
        const token = accessTokenMemory && original.headers.Authorization !== `Bearer ${accessTokenMemory}`
          ? accessTokenMemory : await renewSession()
        original.headers.Authorization = `Bearer ${token}`
        return http(original)
      } catch (refreshError) {
        return Promise.reject(refreshError)
      }
    }

    // Platform staff reach this with an AAL1 session (password only).  The
    // server answers 403 until a TOTP code has been verified, so send them to
    // the verification page instead of leaving a half-empty dashboard.
    const detail = error.response?.data?.detail
    if (
      error.response?.status === 403 &&
      typeof detail === 'string' &&
      detail.includes('مصادقة متعددة العوامل') &&
      !window.location.pathname.startsWith('/auth/mfa')
    ) {
      window.location.assign('/auth/mfa')
    }

    return Promise.reject(error)
  }
)

export default http
