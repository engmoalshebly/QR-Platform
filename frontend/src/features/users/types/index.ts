export interface UserMember {
  tenant_id: string
  user_id: string
  email?: string
  role: 'owner' | 'admin' | 'member' | 'viewer'
  status: 'active' | 'invited' | 'disabled'
  full_name?: string | null
  avatar_url?: string | null
  created_at: string
  updated_at?: string
}

// ── API Requests ──
export interface CreateMemberRequest {
  email: string
  full_name: string
  temporary_password?: string
  role: 'admin' | 'member' | 'viewer'
}

export interface MemberInviteResponse {
  message: string
  invite_id: string
  email: string
  role: 'admin' | 'member' | 'viewer'
  status: string
  expires_at: string
}

export interface UpdateMemberRequest {
  role?: 'owner' | 'admin' | 'member' | 'viewer'
  status?: 'active' | 'invited' | 'disabled'
}

export interface BulkUpdateMembersRequest {
  user_ids: string[]
  role?: 'admin' | 'member' | 'viewer'
  status?: 'active' | 'disabled'
}

// ── Filters ──
export interface MemberFilters {
  search?: string
  role?: string[]
  status?: string[]
  dateRange?: 'all' | '7d' | '30d' | '90d'
}
