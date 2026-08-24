import http from '@services/http/client'

export type BookingStatus = 'pending' | 'needs_information' | 'accepted' | 'in_progress' | 'rejected' | 'cancelled' | 'completed' | 'reopened'

export interface OrganizerTeam {
  tenant_id: string
  name: string
  slug: string
  status: string
  org_type?: string
  description?: string
  city?: string
  country?: string
  website?: string
  phone?: string
  contact_handle?: string
  completed_bookings: number
}

export interface Booking {
  id: string
  event_id?: string
  requester_tenant_id: string
  provider_tenant_id: string
  requester_name: string
  provider_name: string
  title: string
  event_type: string
  starts_at: string
  ends_at: string
  guest_count: number
  location?: string
  contact_name: string
  contact_phone: string
  contact_email?: string
  services?: string
  notes?: string
  status: BookingStatus
  response_note?: string
  created_at: string
  event_description?: string
  event_status?: string
  event_timezone?: string
  event_map_url?: string
  event_cover_image_url?: string
}

export interface BookingCreate {
  provider_tenant_id: string
  event_id: string
  contact_phone: string
  services?: string
  notes?: string
}

export interface BookingGroup {
  id: string
  name: string
  description?: string
  color: string
  members_count: number
  assignments: BookingGroupAssignment[]
}

export interface BookingGroupAssignment {
  operation_id: string
  title: string
  status: string
  assigned_at: string
}

export interface BookingGroupMember {
  user_id: string
  full_name?: string
  avatar_url?: string
  phone?: string
  email?: string
  tenant_role: string
  status: string
  created_at: string
}

export const bookingsAPI = {
  context: async () => (await http.get<{ is_team_manager: boolean; team_tenant_id?: string | null }>('/bookings/context')).data,
  teams: async () => (await http.get<OrganizerTeam[]>('/bookings/organizer-teams')).data,
  create: async (body: BookingCreate) => (await http.post<Booking>('/bookings', body)).data,
  sent: async () => (await http.get<Booking[]>('/bookings/sent')).data,
  inbox: async () => (await http.get<Booking[]>('/bookings/inbox')).data,
  analytics: async () => (await http.get<Record<string, number>>('/bookings/analytics')).data,
  respond: async (id: string, action: 'accepted' | 'rejected' | 'needs_information', note?: string) =>
    (await http.post<Booking>(`/bookings/${id}/respond`, { action, note })).data,
  start: async (id: string) =>
    (await http.post<Booking>(`/bookings/${id}/start`, { reason: 'بدء تنفيذ الحفل' })).data,
  complete: async (id: string) => (await http.post<Booking>(`/bookings/${id}/complete`)).data,
  groups: async () => (await http.get<BookingGroup[]>('/bookings/groups')).data,
  createGroup: async (body: { name: string; description?: string; color?: string }) =>
    (await http.post<BookingGroup>('/bookings/groups', body)).data,
  updateGroup: async (groupId: string, body: { name?: string; description?: string; color?: string }) =>
    (await http.patch<BookingGroup>(`/bookings/groups/${groupId}`, body)).data,
  removeGroup: async (groupId: string) =>
    http.delete(`/bookings/groups/${groupId}`),
  groupMembers: async (groupId: string) =>
    (await http.get<BookingGroupMember[]>(`/bookings/groups/${groupId}/members`)).data,
  addGroupMember: async (groupId: string, userId: string) =>
    http.post(`/bookings/groups/${groupId}/members`, { user_id: userId }),
  removeGroupMember: async (groupId: string, userId: string) =>
    http.delete(`/bookings/groups/${groupId}/members/${userId}`),
  assignGroup: async (groupId: string, bookingId: string) =>
    http.post(`/bookings/groups/${groupId}/assign`, { booking_id: bookingId }),
  assignOperation: async (groupId: string, operationId: string) =>
    http.post(`/bookings/groups/${groupId}/assign-operation`, { operation_id: operationId }),
}
