export interface TenantInfo {
  tenant_id: string
  slug: string
  name: string
  tenant_status: string
  plan: string
  role: string
  membership_status: string
  workspace_type: 'institution' | 'organizer'
  linked_tenant_id?: string | null
}

export interface LoginResponse {
  message: string
  user_id?: string
  access_token?: string
  refresh_token?: string
  tenants?: TenantInfo[]
  requires_tenant_selection?: boolean
}

export interface FieldShift {
  shift_id: string
  event_id: string
  gate_id: string
  operation_id: string
  starts_at: string
  ends_at: string
  timezone: string
  status: 'scheduled' | 'active'
  shift_role: 'scanner' | 'supervisor'
  gate_name: string
  gate_name_ar: string | null
  event_title: string
  event_title_ar: string | null
  has_active_device_session: boolean
  can_start: boolean
}

export interface DeviceSession {
  id: string
  shift_id: string
  event_id: string
  gate_id: string
  user_id: string
  device_id: string
  device_name: string | null
  platform: string | null
  app_version: string | null
  status: 'active'
  started_at: string
  last_seen_at: string
  session_token: string
}

export interface StoredFieldSession {
  deviceSession: DeviceSession
  tenantId: string
}

export interface FieldCheckinResult {
  result: string
  message: string
  invitation_id: string | null
  guest_name: string | null
  ticket_class: string | null
  event_title: string | null
  checkin_count: number
  guest_count: number
  remaining_count: number
  entry_count: number
  requires_assistance: boolean
  code_format: string | null
  idempotent: boolean
}

export interface OfflinePackItem {
  code_fingerprint: string
  ticket_class: string
  allowed_count: number
  remaining_count: number
  expires_at: string | null
}

export interface OfflinePack {
  pack_id: string
  shift_id: string
  gate_id: string
  version: number
  fingerprint_salt: string
  valid_from: string
  valid_until: string
  items: OfflinePackItem[]
}

export interface QueuedCheckin {
  client_scan_id: string
  captured_at: string
  raw_code: string
  entry_count: number
  pack_version: number
  scan_method: 'camera' | 'manual' | 'code128'
}

export interface FieldSearchResult {
  id: string
  label: string
  ticket_class: string
  guest_count: number
  checkin_count: number
  remaining_count: number
}
