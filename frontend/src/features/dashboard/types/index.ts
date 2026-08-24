export interface DashboardTenant {
  name: string
  slug: string
  status: string
  plan: string
  created_at: string
  expires_at?: string | null
}

export interface DashboardStats {
  total_events?: number
  active_events?: number
  draft_events?: number
  completed_events?: number
  cancelled_events?: number
  total_guests?: number
  confirmed_guests?: number
  pending_guests?: number
  checked_in_guests?: number
  total_invitations?: number
  sent_invitations?: number
  delivered_invitations?: number
  opened_invitations?: number
  failed_invitations?: number
  accepted_invitations?: number
  declined_invitations?: number
  maybe_invitations?: number
  pending_invitations?: number
  checked_in_invitations?: number
  invited_people?: number
  checked_in_people?: number
  total_members?: number
  active_members?: number
  pending_invites?: number
  total_templates?: number
  total_roles?: number
  total_flags?: number
  enabled_flags?: number
  total_audit_entries?: number
  audit_24h?: number
  audit_7d?: number
}

export interface DashboardSubscription {
  sub_status: string
  plan_name: string
  plan_code: string
  price_monthly: number
  current_period_start?: string | null
  current_period_end?: string | null
  trial_ends_at?: string | null
  cancel_at_period_end: boolean
}

export interface DashboardUsageItem {
  key: string
  value: number
}

export interface DashboardActivity {
  action: string
  resource_type?: string | null
  resource_id?: string | null
  actor_name?: string | null
  created_at: string
  ip_address?: string | null
}

export interface DashboardTopEvent {
  event_id: string
  event_name: string
  status: string
  total_invitations: number
  checked_in: number
  confirmed: number
  event_date?: string | null
}

export interface DashboardMember {
  full_name?: string | null
  avatar_url?: string | null
  role: string
  status: string
  last_login?: string | null
  joined_at: string
}

export interface DashboardAnalytics {
  tenant: DashboardTenant | null
  linked_organizer?: { tenant_id: string; name: string } | null
  members: DashboardStats
  events: DashboardStats
  guests: DashboardStats
  invitations: DashboardStats
  templates: DashboardStats
  subscription: DashboardSubscription | null
  usage: DashboardUsageItem[]
  team_invites: DashboardStats
  roles: DashboardStats
  audit: DashboardStats & { last_activity?: string | null }
  recent_activity: DashboardActivity[]
  settings_count: number
  features: DashboardStats
  top_events: DashboardTopEvent[]
  members_list: DashboardMember[]
  daily_trend: Array<{ day: string; events: number; invitations: number; checkins: number }>
  event_status_distribution: Array<{ status: string; count: number }>
  checkin_quality: {
    total_scans: number
    successful_scans: number
    duplicate_scans: number
    rejected_scans: number
    scan_success_rate: number
    scans_today: number
    scans_7d: number
  }
}
