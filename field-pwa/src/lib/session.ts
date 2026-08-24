import type { LoginResponse, StoredFieldSession, TenantInfo } from '../domain'
import { offlineStore } from './offlineStore'

const KEY = {
  accessToken: 'qentry_field_access_token',
  refreshToken: 'qentry_field_refresh_token',
  tenantId: 'qentry_field_tenant_id',
  fieldSession: 'qentry_field_device_session',
} as const

export const authSession = {
  get accessToken() { return sessionStorage.getItem(KEY.accessToken) },
  get refreshToken() { return sessionStorage.getItem(KEY.refreshToken) },
  get tenantId() { return sessionStorage.getItem(KEY.tenantId) },
  get userId() {
    const token = this.accessToken
    if (!token) return null
    try {
      const payload = token.split('.')[1]
      if (!payload) return null
      const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
      return typeof decoded.sub === 'string' ? decoded.sub : null
    } catch { return null }
  },
  setLogin(response: LoginResponse, tenant: TenantInfo) {
    if (!response.access_token || !response.refresh_token) throw new Error('استجابة الدخول لا تحتوي جلسة صالحة.')
    sessionStorage.setItem(KEY.accessToken, response.access_token)
    sessionStorage.setItem(KEY.refreshToken, response.refresh_token)
    sessionStorage.setItem(KEY.tenantId, tenant.tenant_id)
  },
  setTokens(accessToken: string, refreshToken?: string) {
    sessionStorage.setItem(KEY.accessToken, accessToken)
    if (refreshToken) sessionStorage.setItem(KEY.refreshToken, refreshToken)
  },
  clearLogin() {
    const tenantId = this.tenantId
    sessionStorage.removeItem(KEY.accessToken)
    sessionStorage.removeItem(KEY.refreshToken)
    sessionStorage.removeItem(KEY.tenantId)
    sessionStorage.removeItem(KEY.fieldSession)
    if (tenantId) void offlineStore.clearDeviceSession(tenantId).catch(() => undefined)
  },
  getDeviceSession(): StoredFieldSession | null {
    const raw = sessionStorage.getItem(KEY.fieldSession)
    if (!raw) return null
    try {
      const session = JSON.parse(raw) as StoredFieldSession
      return session.deviceSession.user_id === this.userId ? session : null
    } catch { return null }
  },
  setDeviceSession(session: StoredFieldSession) {
    const currentUserId = this.userId
    if (!currentUserId) throw new Error('لا يمكن حفظ جلسة بوابة من دون هوية المستخدم.')
    sessionStorage.setItem(KEY.fieldSession, JSON.stringify(session))
    void offlineStore.saveDeviceSession(session, currentUserId).catch(() => undefined)
  },
  clearDeviceSession() {
    const tenantId = this.tenantId
    sessionStorage.removeItem(KEY.fieldSession)
    if (tenantId) void offlineStore.clearDeviceSession(tenantId).catch(() => undefined)
  },
  async restoreDeviceSession(): Promise<StoredFieldSession | null> {
    const tenantId = this.tenantId
    const userId = this.userId
    if (!tenantId || !userId || !this.accessToken) return null
    const stored = await offlineStore.getDeviceSession(tenantId).catch(() => null)
    const restored = stored?.session
    if (stored?.userId === userId && restored?.tenantId === tenantId && restored.deviceSession.user_id === userId) {
      sessionStorage.setItem(KEY.fieldSession, JSON.stringify(restored))
      return restored
    }
    return null
  },
}
