import type { DeviceSession, FieldCheckinResult, FieldSearchResult, FieldShift, LoginResponse, OfflinePack, QueuedCheckin } from '../domain'
import { authSession } from './session'

const API_BASE = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function parseError(response: Response): Promise<string> {
  const body = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null
  const detail = body?.detail ?? body?.message
  if (typeof detail === 'string') return detail
  return response.status === 0 ? 'تعذر الاتصال بالشبكة.' : 'تعذر تنفيذ الطلب. حاول مرة أخرى.'
}

let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (refreshInFlight) return refreshInFlight
  const refreshToken = authSession.refreshToken
  if (!refreshToken) throw new ApiError('انتهت جلسة الدخول. سجل الدخول مجدداً.', 401)
  refreshInFlight = fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify({ refresh_token: refreshToken }),
  }).then(async (response) => {
    if (!response.ok) throw new ApiError(await parseError(response), response.status)
    const result = await response.json() as LoginResponse
    if (!result.access_token) throw new ApiError('تعذر تجديد جلسة الدخول.', 401)
    authSession.setTokens(result.access_token, result.refresh_token)
    return result.access_token
  }).finally(() => { refreshInFlight = null })
  return refreshInFlight
}

async function request<T>(path: string, init: RequestInit = {}, retryAfterRefresh = true): Promise<T> {
  const token = authSession.accessToken
  const tenantId = authSession.tenantId
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (tenantId) headers.set('X-Tenant-ID', tenantId)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, cache: 'no-store' })
  } catch {
    throw new ApiError('لا يوجد اتصال بالخادم. تحقق من الشبكة ثم حاول مجدداً.', 0)
  }
  if (response.status === 401 && retryAfterRefresh && !path.startsWith('/auth/')) {
    try {
      await refreshAccessToken()
      return request<T>(path, init, false)
    } catch (error) {
      authSession.clearLogin()
      throw error
    }
  }
  if (!response.ok) throw new ApiError(await parseError(response), response.status)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function fieldHeaders(): HeadersInit {
  const session = authSession.getDeviceSession()
  if (!session) throw new ApiError('ابدأ جلسة البوابة أولاً.', 403)
  return {
    'X-Field-Device-Session': session.deviceSession.id,
    'X-Field-Device-Token': session.deviceSession.session_token,
  }
}

export const fieldApi = {
  login: (email: string, password: string, tenantId?: string) => request<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, tenant_id: tenantId }),
  }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  shifts: (date: string) => request<FieldShift[]>(`/mobile/shifts?date=${encodeURIComponent(date)}`),
  startDeviceSession: (body: {
    shift_id: string
    device_id: string
    device_name: string
    platform: string
    app_version: string
  }) => request<DeviceSession>('/mobile/device-sessions', { method: 'POST', body: JSON.stringify(body) }),
  closeDeviceSession: (id: string) => request<{ id: string; status: string }>(`/mobile/device-sessions/${id}/close`, { method: 'POST' }),
  downloadPack: (shiftId: string) => request<OfflinePack>(`/mobile/checkin-pack/${shiftId}`, { headers: fieldHeaders() }),
  checkin: (body: {
    raw_code?: string
    invitation_id?: string
    entry_count: number
    client_scan_id: string
    client_captured_at: string
    scan_method: 'camera' | 'manual' | 'code128'
  }) => request<FieldCheckinResult>('/mobile/checkins', { method: 'POST', headers: fieldHeaders(), body: JSON.stringify(body) }),
  syncCheckins: (packId: string, items: QueuedCheckin[]) => request<{ pack_id: string; results: FieldCheckinResult[] }>('/mobile/checkins/sync', {
    method: 'POST', headers: fieldHeaders(), body: JSON.stringify({ pack_id: packId, items }),
  }),
  searchInvitations: (query: string) => request<FieldSearchResult[]>(`/mobile/invitations/search?query=${encodeURIComponent(query)}`, { headers: fieldHeaders() }),
  requestAssistance: (body: { assistance_type: 'duplicate' | 'manual_confirmation' | 'access' | 'device' | 'offline_conflict' | 'other'; note?: string }) => request<{ id: string; status: string; created_at: string }>('/mobile/assistance', { method: 'POST', headers: fieldHeaders(), body: JSON.stringify(body) }),
}
