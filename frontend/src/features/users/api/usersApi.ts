import http from '@services/http/client'
import type {
  UserMember,
  CreateMemberRequest,
  MemberInviteResponse,
  UpdateMemberRequest,
  BulkUpdateMembersRequest,
  WorkspaceInvite,
} from '../types'

export const usersAPI = {
  invites: async (): Promise<WorkspaceInvite[]> => {
    const { data } = await http.get<WorkspaceInvite[]>('/invites')
    return data
  },
  resendInvite: async (id: string): Promise<{ message: string }> => {
    const { data } = await http.post<{ message: string }>(`/invites/${id}/resend`)
    return data
  },
  revokeInvite: async (id: string): Promise<void> => {
    await http.delete(`/invites/${id}`)
  },
  // ── Read ──
  list: async (): Promise<UserMember[]> => {
    const { data } = await http.get<UserMember[]>('/tenants/current/members')
    return data
  },

  getById: async (userId: string): Promise<UserMember> => {
    const { data } = await http.get<UserMember>(`/tenants/current/members/${userId}`)
    return data
  },

  // ── Create ──
  create: async (body: CreateMemberRequest): Promise<MemberInviteResponse> => {
    const { data } = await http.post<MemberInviteResponse>('/tenants/current/members', body)
    return data
  },

  addDirect: async (body: Pick<CreateMemberRequest, 'email' | 'full_name' | 'temporary_password' | 'role'>): Promise<UserMember> => {
    const { data } = await http.post<UserMember>('/tenants/current/members/direct', body)
    return data
  },

  // ── Update ──
  update: async (userId: string, body: UpdateMemberRequest): Promise<UserMember> => {
    const { data } = await http.patch<UserMember>(`/tenants/current/members/${userId}`, body)
    return data
  },

  // ── Bulk Update ──
  bulkUpdate: async (body: BulkUpdateMembersRequest): Promise<void> => {
    await http.patch('/tenants/current/members/bulk', body)
  },

  // ── Delete ──
  remove: async (userId: string): Promise<void> => {
    await http.delete(`/tenants/current/members/${userId}`)
  },

  // ── Bulk Delete ──
  bulkRemove: async (userIds: string[]): Promise<void> => {
    await http.post('/tenants/current/members/bulk-delete', { user_ids: userIds })
  },

  // ── Actions ──
  disable: async (userId: string): Promise<void> => {
    await usersAPI.update(userId, { status: 'disabled' })
  },

  activate: async (userId: string): Promise<void> => {
    await usersAPI.update(userId, { status: 'active' })
  },

  changeRole: async (userId: string, role: UserMember['role']): Promise<void> => {
    await usersAPI.update(userId, { role })
  },
}
