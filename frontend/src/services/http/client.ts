import axios from 'axios'

export { getApiErrorCode, getApiErrorMessage } from './apiErrors'
export type { LimitErrorCode } from './apiErrors'

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'
// The access token lives in memory only: a script that reads storage cannot take
// it.  The refresh token is an HttpOnly cookie that the browser sends on its own.
// Restore the cookie session before sending requests after a reload.
let accessTokenMemory: string | null = null
export const setAccessToken = (token: string | null) => {
  accessTokenMemory = token
}

// Header that a cross-site form cannot send.  The server requires it before it
// rotates a session from the cookie.
const CSRF_HEADERS = { 'X-Requested-With': 'qentry' } as const

let refreshPromise: Promise<string> | null = null
const renewSession = (): Promise<string> => {
  if (!refreshPromise) {
    refreshPromise = axios.post(`${BASE_URL}/auth/refresh`, {}, {
      withCredentials: true,
      timeout: 30_000,
      headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS },
    }).then(({ data }) => {
      if (typeof data.access_token !== 'string' || !data.access_token) {
        throw new Error('Missing access token in refresh response')
      }
      setAccessToken(data.access_token)
      return data.access_token as string
    }).catch(error => {
      if ([401, 403].includes(error.response?.status)) {
        Object.values(STORAGE).forEach(key => sessionStorage.removeItem(key))
        sessionStorage.removeItem('qentry-auth')
        setAccessToken(null)
        window.location.assign('/auth/login')
      }
      throw error
    }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
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
