import axios from 'axios'

/** Convert FastAPI's string or structured `detail` payload into readable UI text. */
export const getApiErrorMessage = (error: unknown, fallback = 'تعذر إكمال الطلب') => {
  const candidate = error as {
    response?: { data?: { detail?: unknown } }
    message?: unknown
  }
  const detail = candidate?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const payload = detail as { message?: unknown; issues?: unknown; fields?: unknown }
    const message = typeof payload.message === 'string' ? payload.message.trim() : ''
    const issues = Array.isArray(payload.issues)
      ? payload.issues.filter((issue): issue is string => typeof issue === 'string' && Boolean(issue.trim()))
      : []
    const fields = Array.isArray(payload.fields)
      ? payload.fields.filter((field): field is string => typeof field === 'string' && Boolean(field.trim()))
      : []
    const details = [...issues, ...fields]
    if (message || details.length) {
      return [message, ...details.map((item) => `• ${item}`)].filter(Boolean).join('\n')
    }
  }

  return typeof candidate?.message === 'string' && candidate.message.trim()
    ? candidate.message
    : fallback
}

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'
// The access token lives in memory only: a script that reads storage cannot take
// it.  The refresh token is an HttpOnly cookie that the browser sends on its own.
// A reload therefore starts with no access token; the first 401 renews it.
let accessTokenMemory: string | null = null
export const setAccessToken = (token: string | null) => {
  accessTokenMemory = token
}

// Header that a cross-site form cannot send.  The server requires it before it
// rotates a session from the cookie.
const CSRF_HEADERS = { 'X-Requested-With': 'qentry' } as const

/** Download a protected file without exposing the access token in a URL. */
export const downloadAuthenticatedFile = async (url: string, fallbackName = 'download') => {
  const response = await http.get(url, { responseType: 'blob' })
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
http.interceptors.request.use((config) => {
  const token    = accessTokenMemory
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

    if (error.response?.status === 401 && !original._retry && !isAuthRoute) {
      original._retry = true
      try {
        // The refresh cookie is sent by the browser.  No token is read here.
        const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {}, {
          withCredentials: true,
          headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS },
        })

        setAccessToken(data.access_token)

        original.headers.Authorization = `Bearer ${data.access_token}`
        return http(original)
      } catch {
        // Clear storage and redirect to login
        Object.values(STORAGE).forEach(k => sessionStorage.removeItem(k))
        setAccessToken(null)
        window.location.href = '/auth/login'
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
