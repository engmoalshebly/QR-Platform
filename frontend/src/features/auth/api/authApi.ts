import http, { STORAGE, setAccessToken, setRefreshToken } from '@services/http/client'
import type {
  AuthResponse, LoginRequest, SignupRequest,
  SendOtpRequest, VerifyOtpRequest, ConfirmNewPasswordRequest, OtpResponse,
  MeResponse, OrgRequest, OrgRequestResponse,
} from '../types'

export const authAPI = {
  // POST /auth/login
  login: async (body: LoginRequest): Promise<AuthResponse> => {
    const { data } = await http.post<AuthResponse>('/auth/login', body)

    if (data.access_token)  setAccessToken(data.access_token)
    if (data.refresh_token) setRefreshToken(data.refresh_token)
    if (!data.requires_tenant_selection && data.tenants?.[0]) {
      sessionStorage.setItem(STORAGE.TENANT_ID, data.tenants[0].tenant_id)
    } else {
      // A platform administrator has no workspace.  Do not carry a previous
      // user's tenant context into this session.
      sessionStorage.removeItem(STORAGE.TENANT_ID)
    }

    return data
  },

  // POST /auth/signup
  signup: async (body: SignupRequest): Promise<AuthResponse> => {
    const { data } = await http.post<AuthResponse>('/auth/signup', body)
    return data
  },

  // POST /auth/org-request (organizer-team registration request)
  orgRequest: async (body: OrgRequest): Promise<OrgRequestResponse> => {
    const { data } = await http.post<OrgRequestResponse>('/auth/org-request', body)
    return data
  },

  // POST /auth/logout
  logout: async (): Promise<void> => {
    try { await http.post('/auth/logout') } finally {
      setRefreshToken(null)
      Object.values(STORAGE).forEach(k => sessionStorage.removeItem(k))
    }
  },

  // GET /auth/me
  me: async (): Promise<MeResponse> => {
    const { data } = await http.get<MeResponse>('/auth/me')
    return data
  },

  // ── OTP Password Reset (3 steps) ──

  // POST /auth/password-reset/send-otp
  sendOtp: async (body: SendOtpRequest): Promise<OtpResponse> => {
    const { data } = await http.post<OtpResponse>('/auth/password-reset/send-otp', body)
    return data
  },

  // POST /auth/password-reset/verify-otp
  verifyOtp: async (body: VerifyOtpRequest): Promise<OtpResponse> => {
    const { data } = await http.post<OtpResponse>('/auth/password-reset/verify-otp', body)
    return data
  },

  // POST /auth/password-reset/confirm-new
  confirmNewPassword: async (body: ConfirmNewPasswordRequest): Promise<OtpResponse> => {
    const { data } = await http.post<OtpResponse>('/auth/password-reset/confirm-new', body)
    return data
  },

  // POST /auth/refresh
  refresh: async (refresh_token: string): Promise<AuthResponse> => {
    const { data } = await http.post<AuthResponse>('/auth/refresh', { refresh_token })
    return data
  },
  uploadOrgDocument: async (file: File): Promise<{ file_key: string; file_name: string }> => {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post('/auth/org-request/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },
}
