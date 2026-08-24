import http from '@services/http/client'

export interface PlatformKPIs {
  total_tenants: number
  active_tenants: number
  trial_tenants: number
  suspended_tenants: number
  cancelled_tenants: number
  new_tenants_30d: number
  new_tenants_7d: number
  total_users: number
  new_users_30d: number
  total_active_memberships: number
  active_subscriptions: number
  total_events: number
  total_invitations: number
  total_guests: number
}

export interface PlatformRevenue {
  mrr: number
  arr: number
  avg_revenue_per_tenant: number
  paying_tenants: number
}

export interface PlanDistribution {
  plan: string
  plan_name: string
  badge_color: string
  count: number
}

export interface StatusDistribution {
  status: string
  count: number
}

export interface TrendPoint {
  date: string
  new_tenants: number
  new_users: number
}

export interface RecentTenant {
  id: string
  slug: string
  name: string
  status: string
  plan: string
  created_at: string
  members_count: number
}

export interface TopTenant {
  id: string
  slug: string
  name: string
  plan: string
  events_count: number
  invitations_count: number
  members_count: number
}

export interface PlatformAnalytics {
  kpis: PlatformKPIs
  revenue: PlatformRevenue
  plan_distribution: PlanDistribution[]
  status_distribution: StatusDistribution[]
  trend_30d: TrendPoint[]
  recent_tenants: RecentTenant[]
  top_tenants: TopTenant[]
}

export interface PlatformUser {
  id: string
  full_name: string
  avatar_url: string | null
  is_staff: boolean
  created_at: string
  last_login_at: string | null
  tenants_count: number
  email: string
}

export interface PlatformStaff {
  id: string
  email: string
  full_name: string | null
  is_staff: boolean
}

export interface PlatformTenant {
  id: string
  slug: string
  name: string
  status: string
  plan: string
  workspace_type?: 'institution' | 'organizer'
  created_by: string | null
  metadata: Record<string, unknown> | null
  expires_at: string | null
  created_at: string
  updated_at: string
  members_count: number
  linked_tenant_id?: string | null
  linked_tenant_name?: string | null
  is_workspace_group?: boolean
}

export interface PlatformTenantMember {
  user_id: string
  full_name: string | null
  avatar_url: string | null
  role: string
  status: string
  created_at: string
  assigned_roles: string[]
}

export interface PlatformTenantEvent {
  id: string
  title: string
  status: string
  start_date: string
  end_date: string | null
  location: string | null
  invitations_count: number
}

export interface PlatformTenantAnalytics {
  events_total: number
  events_draft: number
  events_live: number
  events_upcoming: number
  vip_capacity: number
  normal_capacity: number
  invitations_total: number
  guests_total: number
  activity_30d: number
}

export interface PlatformTenantActivity {
  id: string
  action: string
  resource_type: string | null
  resource_id: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  actor_name: string | null
}

export interface PlatformTenantDetail {
  tenant: PlatformTenant & {
    events_count: number
    invitations_count: number
    guests_count: number
  }
  workspace_group: {
    is_linked: boolean
    organizer_tenant_id: string
    institution_tenant_id: string | null
    institution_name: string | null
    billing_tenant_id: string
  }
  subscription: {
    sub_status: string
    plan_code: string
    plan_name: string
    price_monthly: number
    current_period_end: string | null
    trial_ends_at: string | null
  } | null
  members: PlatformTenantMember[]
  analytics: PlatformTenantAnalytics
  recent_events: PlatformTenantEvent[]
  roles: Array<PlatformRoleInfo & { members_count: number }>
  recent_activity: PlatformTenantActivity[]
}

export interface PlatformSubscription {
  id: string
  tenant_id: string
  tenant_name: string
  tenant_slug: string
  sub_status: string
  plan_code: string
  plan_name: string
  price_monthly: number
  current_period_start: string
  current_period_end: string
  trial_ends_at: string | null
  created_at: string
}

export interface AuditLogEntry {
  id: string
  tenant_id: string | null
  tenant_name: string | null
  actor_user_id: string | null
  actor_name: string | null
  action: string
  resource_type: string
  resource_id: string
  metadata: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface PlanOverviewItem {
  id: string
  code: string
  name: string
  description: string
  subtitle: string
  price_monthly: number
  price_yearly: number
  currency: string
  badge_color: string
  is_popular: boolean
  is_active: boolean
  sort_order: number
  active_subscribers: number
  total_subscribers: number
}

export interface PlatformRoleInfo {
  id: string
  tenant_id: string
  name: string
  description: string | null
  is_system_role: boolean
  created_at: string
  permissions: string[] | null
}

export interface AddonItem {
  id: string
  key: string
  label_ar: string
  label_en: string
  unit_ar: string
  icon: string
  price_per_unit: number
  step: number
  category: string
  sort_order: number
}

export interface OrgRequest {
  id: string
  status: string
  full_name: string
  email: string
  phone?: string | null
  org_name: string
  org_type?: string | null
  description?: string | null
  city?: string | null
  country?: string | null
  website?: string | null
  contact_handle?: string | null
  expected_events_per_month?: number | null
  expected_attendees?: number | null
  requested_plan_code?: string | null
  proof_url?: string | null
  documents_url?: string | null
  notes?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  created_tenant_id?: string | null
  created_at: string
}

export const platformAPI = {
  analytics: async (): Promise<PlatformAnalytics> => {
    const { data } = await http.get<PlatformAnalytics>('/platform/analytics')
    return data
  },

  // Tenants
  listTenants: async (params?: { status?: string; plan?: string; search?: string; limit?: number; offset?: number }) => {
    const { data } = await http.get<PlatformTenant[]>('/platform/tenants', { params })
    return data
  },
  getTenant: async (id: string): Promise<PlatformTenantDetail> => {
    const { data } = await http.get<PlatformTenantDetail>(`/platform/tenants/${id}`)
    return data
  },
  suspendTenant: async (id: string) => {
    const { data } = await http.post(`/platform/tenants/${id}/suspend`)
    return data
  },
  activateTenant: async (id: string) => {
    const { data } = await http.post(`/platform/tenants/${id}/activate`)
    return data
  },
  cancelTenant: async (id: string) => {
    const { data } = await http.post(`/platform/tenants/${id}/cancel`)
    return data
  },

  // Users
  listUsers: async (params?: { search?: string; limit?: number; offset?: number }) => {
    const { data } = await http.get<{ users: PlatformUser[]; total: number }>('/platform/users', { params })
    return data
  },
  getUser: async (id: string) => {
    const { data } = await http.get(`/platform/users/${id}`)
    return data
  },
  listStaff: async () => {
    const { data } = await http.get<PlatformStaff[]>('/platform/staff')
    return data
  },
  grantStaff: async (email: string) => {
    const { data } = await http.post<PlatformStaff>('/platform/staff', { email })
    return data
  },
  revokeStaff: async (id: string) => {
    await http.delete(`/platform/staff/${id}`)
  },

  // Subscriptions
  listSubscriptions: async (params?: { status?: string; plan_code?: string; limit?: number; offset?: number }) => {
    const { data } = await http.get<PlatformSubscription[]>('/platform/subscriptions', { params })
    return data
  },

  // Audit
  listAuditLogs: async (params?: { action?: string; tenant_id?: string; limit?: number; offset?: number }) => {
    const { data } = await http.get<AuditLogEntry[]>('/platform/audit-logs', { params })
    return data
  },

  // Plans
  plansOverview: async () => {
    const { data } = await http.get<{ plans: PlanOverviewItem[]; addons: AddonItem[]; custom_plans: { active_custom: number; total_custom: number } }>('/platform/plans-overview')
    return data
  },
  updatePlan: async (id: string, body: Partial<PlanOverviewItem>) => {
    const { data } = await http.patch<{ message: string }>(`/platform/plans/${id}`, body)
    return data
  },
  getPlanLimits: async (id: string) => {
    const { data } = await http.get<{ key: string; value: number; period: string }[]>(`/platform/plans/${id}/limits`)
    return data
  },
  updatePlanLimits: async (id: string, limits: { key: string; value: number; period: string }[]) => {
    const { data } = await http.put<{ message: string }>(`/platform/plans/${id}/limits`, limits)
    return data
  },
  updateAddon: async (id: string, body: Partial<AddonItem>) => {
    const { data } = await http.patch<{ message: string }>(`/platform/addons/${id}`, body)
    return data
  },

  // Roles (platform staff only)
  listPermissions: async () => {
    const { data } = await http.get<{ key: string; description: string | null }[]>('/platform/permissions')
    return data
  },
  listTenantRoles: async (tenantId: string) => {
    const { data } = await http.get<PlatformRoleInfo[]>(`/platform/tenants/${tenantId}/roles`)
    return data
  },
  createTenantRole: async (tenantId: string, body: { name: string; description?: string; permissions: string[] }) => {
    const { data } = await http.post<PlatformRoleInfo>(`/platform/tenants/${tenantId}/roles`, body)
    return data
  },
  updateTenantRole: async (tenantId: string, roleId: string, body: { permissions: string[] }) => {
    const { data } = await http.patch<PlatformRoleInfo>(`/platform/tenants/${tenantId}/roles/${roleId}`, body)
    return data
  },
  deleteTenantRole: async (tenantId: string, roleId: string) => {
    await http.delete(`/platform/tenants/${tenantId}/roles/${roleId}`)
  },

  // Organizer-team registration requests
  listOrgRequests: async (status: string = 'pending') => {
    const { data } = await http.get<OrgRequest[]>('/platform/org-requests', { params: { status } })
    return data
  },
  approveOrgRequest: async (id: string, note?: string) => {
    const { data } = await http.post<OrgRequest>(`/platform/org-requests/${id}/approve`, { note })
    return data
  },
  rejectOrgRequest: async (id: string, note?: string) => {
    const { data } = await http.post<OrgRequest>(`/platform/org-requests/${id}/reject`, { note })
    return data
  },
}
