export interface TenantInfo {
  tenant_id:        string
  slug:             string
  name:             string
  tenant_status:    string
  plan:             string
  role:             string
  membership_status:string
  workspace_type:   'institution' | 'organizer'
  linked_tenant_id?: string | null
}

export interface AuthResponse {
  message:                  string
  user_id?:                 string
  access_token?:            string
  refresh_token?:           string
  tenants?:                 TenantInfo[]
  requires_tenant_selection?:boolean
}

export interface AuthUser {
  id:        string
  email:     string
  full_name: string | null
  avatar_url:string | null
  is_staff:  boolean
}

export interface MeResponse extends AuthUser {
  user_id?:    string
  phone?:      string | null
  tenants?:    TenantInfo[]
  permissions?: string[]
}

export interface AuthState {
  user:    AuthUser | null
  tenants: TenantInfo[]
  currentTenantId: string | null
}

// ── Requests ──
export interface LoginRequest {
  email:      string
  password:   string
  tenant_id?: string
}

export interface SignupRequest {
  email:              string
  password:           string
  full_name?:         string
  organization_name?: string
}

// ── Organizer-team registration request (awaits platform approval) ──
export interface OrgRequest {
  full_name:                  string
  email:                      string
  password:                   string
  phone?:                     string
  org_name:                   string
  org_type?:                  string
  description?:               string
  city?:                      string
  country?:                   string
  website?:                   string
  contact_handle?:            string
  expected_events_per_month?: number
  expected_attendees?:        number
  requested_plan_code?:       string
  proof_url?:                 string
  documents_url?:             string
  notes?:                     string
}

export interface OrgRequestResponse {
  message: string
}

export interface OrgRequestStatusResponse {
  request_id: string
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  org_name: string
  review_note?: string | null
  created_at: string
}

export interface ForgotPasswordRequest {
  email: string
}

// ── OTP Password Reset ──
export interface SendOtpRequest {
  email: string
}

export interface VerifyOtpRequest {
  email:    string
  otp_code: string
}

export interface ConfirmNewPasswordRequest {
  reset_token:  string
  new_password: string
}

export interface OtpResponse {
  message: string
  reset_token?: string
}
