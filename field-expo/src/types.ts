export type TenantInfo = {
  tenant_id: string;
  name: string;
  slug: string;
  role: string;
  workspace_type: "institution" | "organizer";
};

export type LoginResponse = {
  message?: string;
  user_id?: string;
  access_token?: string;
  refresh_token?: string;
  tenants?: TenantInfo[];
  requires_tenant_selection?: boolean;
};

export type FieldShift = {
  shift_id: string;
  event_id: string;
  gate_id: string;
  operation_id: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  status: "scheduled" | "active";
  shift_role: "scanner" | "supervisor";
  gate_name: string;
  gate_name_ar: string | null;
  event_title: string;
  event_title_ar: string | null;
  has_active_device_session: boolean;
  can_start: boolean;
};

export type FieldEventCard = {
  event_id: string;
  operation_id: string;
  title: string;
  title_ar: string | null;
  start_date: string;
  end_date: string | null;
  timezone: string;
  venue_name: string | null;
  venue_name_ar: string | null;
  assigned_gate_count: number;
  assigned_shift_count: number;
  is_available_today: boolean;
  has_active_device_session: boolean;
};

export type FieldBriefingShift = FieldShift & {
  has_active_device_session: boolean;
};

export type FieldEventBriefing = {
  event_id: string;
  title: string;
  title_ar: string | null;
  start_date: string;
  end_date: string | null;
  timezone: string;
  venue_name: string | null;
  venue_name_ar: string | null;
  description: string | null;
  is_available_today: boolean;
  statistics: {
    total_invitations: number;
    vip_invitations: number;
    normal_invitations: number;
    expected_guests: number;
    checked_in_guests: number;
  };
  shifts: FieldBriefingShift[];
};

export type DeviceSession = {
  id: string;
  shift_id: string;
  event_id: string;
  gate_id: string;
  user_id: string;
  device_id: string;
  device_name: string | null;
  platform: string | null;
  app_version: string | null;
  status: "active";
  started_at: string;
  last_seen_at: string;
  session_token: string;
};

export type FieldCheckinResult = {
  result: string;
  message: string;
  invitation_id: string | null;
  guest_name: string | null;
  ticket_class: string | null;
  event_title: string | null;
  checkin_count: number;
  guest_count: number;
  remaining_count: number;
  entry_count: number;
  requires_assistance: boolean;
  code_format: string | null;
  idempotent: boolean;
};

export type FieldSearchResult = {
  id: string;
  label: string;
  ticket_class: string;
  guest_count: number;
  checkin_count: number;
  remaining_count: number;
};

export type FieldMobileSettings = {
  user: {
    id: string;
    full_name: string | null;
    email: string | null;
    phone: string | null;
    avatar_url: string | null;
    status: string | null;
    email_verified: boolean;
  };
  workspace: {
    tenant_id: string;
    name: string;
    slug: string;
    plan: string | null;
    workspace_type: "institution" | "organizer";
    membership_role: string;
    membership_status: string;
  };
  permissions: string[];
  device: {
    device_id: string | null;
    active_session: {
      id: string;
      device_id: string;
      device_name: string | null;
      platform: string | null;
      app_version: string | null;
      started_at: string;
      last_seen_at: string;
      gate_name: string;
      gate_name_ar: string | null;
      event_title: string;
      event_title_ar: string | null;
    } | null;
  };
};

export type StoredAuth = {
  accessToken: string;
  refreshToken: string;
  tenant: TenantInfo;
};

export type StoredFieldSession = {
  session: DeviceSession;
  selectedShift: FieldShift;
};
