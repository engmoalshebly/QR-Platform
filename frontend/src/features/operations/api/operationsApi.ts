import http from '@services/http/client'

export type OperationRole = 'manager' | 'lead' | 'member'
export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done'

export interface OperationTask { id:string; title:string; description?:string; status:TaskStatus; priority:string; assigned_to?:string; assignee_name?:string; due_at?:string; start_at?:string; approval_required?:boolean; approved_by?:string }
export interface OperationMember { user_id:string; role:OperationRole; full_name?:string; email:string }
export interface OperationAttachment { id:string; file_name:string; content_type:string; size_bytes:number; download_url?:string; created_at:string }
export interface OperationActivity { id:number; action:string; actor_name?:string; details:Record<string, unknown>; created_at:string }
export interface OperationSummary { id:string; booking_id?:string | null; title:string; requester_name:string; starts_at:string; ends_at?:string | null; location?:string; guest_count:number; status:string; progress:number; tasks_count:number; tasks_done:number }
export interface OperationDetail extends OperationSummary { my_role:OperationRole; event_type?:string; services?:string; notes?:string; contact_name?:string | null; contact_phone?:string | null; contact_email?:string; event_description?:string; venue_map_url?:string; event_id?:string; tasks:OperationTask[]; members:OperationMember[]; attachments:OperationAttachment[]; activity:OperationActivity[] }

export interface EventInsights {
  my_role: OperationRole
  event_id: string
  booking?: { guest_count?: number; title?: string; contact_name?: string; contact_phone?: string; contact_email?: string }
  invitations: Record<string, number>
  gates: Array<{ id:string; name?:string; name_ar?:string; is_active:boolean; scans:number }>
  recent_scans: Array<{ id:string; result:string; scan_method?:string; created_at:string; guest_name?:string; guest_name_ar?:string; ticket_class?:string; scanner_name?:string; gate_name?:string }>
  guests: Array<{ id:string; invitation_id:string; full_name?:string; full_name_ar?:string; phone?:string; email?:string; ticket_class?:string; rsvp_status?:string; checked_in_at?:string }>
  scan_leaderboard: Array<{ scanner_name?:string; accepted_scans:number }>
}

export type GateShiftStatus = 'scheduled' | 'active' | 'completed' | 'cancelled'
export type GateShiftRole = 'scanner' | 'supervisor'

export interface GateShift {
  id: string
  event_id: string
  gate_id: string
  operation_id: string
  gate_name?: string
  gate_name_ar?: string | null
  starts_at: string
  ends_at: string
  timezone: string
  status: GateShiftStatus
  supervisor_user_id: string
  supervisor_name?: string
  assigned_members?: number
  scanners?: number
  supervisors?: number
}

export interface GateShiftMember {
  user_id: string
  full_name?: string
  avatar_url?: string | null
  role: GateShiftRole
  assignment_source: 'direct' | 'group_snapshot'
  source_group_id?: string | null
  conflict_override_reason?: string | null
  is_active: boolean
  assigned_at: string
}

export interface GateShiftGroup {
  group_id: string
  name: string
  color?: string
  role: GateShiftRole
  snapshot_at: string
  snapshotted_members: number
}

export interface GateDeviceSession {
  id: string
  user_id: string
  device_id: string
  device_name?: string | null
  platform?: string | null
  app_version?: string | null
  status: 'active' | 'closed' | 'revoked'
  started_at: string
  last_seen_at: string
  closed_at?: string | null
  revoked_at?: string | null
  closure_reason?: string | null
}

export const operationsAPI = {
  list: async () => (await http.get<OperationSummary[]>('/operations')).data,
  detail: async (id:string) => (await http.get<OperationDetail>(`/operations/${id}`)).data,
  eventInsights: async (id:string, scope: 'overview' | 'guests' | 'gates' | 'live' = 'overview') =>
    (await http.get<EventInsights>(`/operations/${id}/event-insights`, { params: { scope } })).data,
  createTask: async (id:string, body:Partial<OperationTask>) => (await http.post(`/operations/${id}/tasks`, body)).data,
  updateTask: async (id:string, taskId:string, body:Partial<OperationTask>) => (await http.patch(`/operations/${id}/tasks/${taskId}`, body)).data,
  setMember: async (id:string, user_id:string, role:OperationRole) => http.post(`/operations/${id}/members`, { user_id, role }),
  removeMember: async (id:string, user_id:string) => http.delete(`/operations/${id}/members/${user_id}`),
  upload: async (id:string, file:File) => {
    const form = new FormData(); form.append('file', file)
    return (await http.post(`/operations/${id}/attachments`, form)).data
  },
  gateShifts: async (eventId: string, gateId?: string) =>
    (await http.get<GateShift[]>('/gate-shifts', { params: { event_id: eventId, gate_id: gateId } })).data,
  gateShift: async (shiftId: string) =>
    (await http.get<{ shift: GateShift; members: GateShiftMember[]; groups: GateShiftGroup[] }>(`/gate-shifts/${shiftId}`)).data,
  createGateShift: async (body: {
    event_id: string; gate_id: string; operation_id: string; starts_at: string; ends_at: string;
    timezone: string; supervisor_user_id: string
  }) => (await http.post<GateShift>('/gate-shifts', body)).data,
  updateGateShift: async (shiftId: string, body: Partial<Pick<GateShift, 'starts_at' | 'ends_at' | 'timezone' | 'supervisor_user_id' | 'status'>> & { cancellation_reason?: string }) =>
    (await http.patch<GateShift>(`/gate-shifts/${shiftId}`, body)).data,
  assignGateShiftMember: async (shiftId: string, body: { user_id: string; role: GateShiftRole; conflict_override_reason?: string }) =>
    (await http.post<GateShiftMember>(`/gate-shifts/${shiftId}/members`, body)).data,
  assignGateShiftGroup: async (shiftId: string, body: { group_id: string; role: GateShiftRole; conflict_override_reason?: string }) =>
    (await http.post(`/gate-shifts/${shiftId}/groups`, body)).data,
  gateShiftDeviceSessions: async (shiftId: string) =>
    (await http.get<GateDeviceSession[]>(`/gate-shifts/${shiftId}/device-sessions`)).data,
  revokeGateShiftDeviceSession: async (shiftId: string, sessionId: string, reason = 'supervisor_revoked') =>
    (await http.post(`/gate-shifts/${shiftId}/device-sessions/${sessionId}/revoke`, undefined, { params: { reason } })).data,
}
