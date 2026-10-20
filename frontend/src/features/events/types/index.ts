export type EventStatus = 'draft' | 'published' | 'active' | 'completed' | 'cancelled'
export type TicketClass = 'vip' | 'normal'

export interface EventCategory {
  id: string
  tenant_id: string | null
  name: string
  name_ar: string | null
  icon: string | null
  color: string | null
  sort_order: number
  is_system: boolean
  created_at: string
}

export interface EventType {
  id: string
  category_id: string
  tenant_id: string | null
  name: string
  name_ar: string | null
  description: string | null
  is_system: boolean
  created_at: string
}

export interface EventModel {
  id: string
  tenant_id: string
  event_type_id: string | null
  category_id: string | null
  title: string
  title_ar: string | null
  description: string | null
  slug: string | null
  start_date: string
  end_date: string | null
  timezone: string
  venue_name: string | null
  venue_name_ar: string | null
  venue_address: string | null
  venue_city: string | null
  venue_country: string | null
  venue_map_url: string | null
  venue_lat: number | null
  venue_lng: number | null
  vip_quota: number
  normal_quota: number
  capacity: number | null
  vip_capacity: number | null
  normal_capacity: number | null
  allow_rsvp: boolean
  allow_plus_one: boolean
  allow_reentry: boolean
  require_name: boolean
  cover_image_url: string | null
  theme_color: string | null
  status: EventStatus
  published_at: string | null
  deleted_at: string | null
  deleted_by: string | null
  created_by: string | null
  team_id: string | null
  metadata: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface EventCreateRequest {
  title: string
  start_date: string
  vip_quota?: number
  normal_quota?: number
  capacity?: number
  vip_capacity?: number
  normal_capacity?: number
  venue_country?: string
  timezone?: string
  allow_rsvp?: boolean
  allow_plus_one?: boolean
  allow_reentry?: boolean
  require_name?: boolean
  theme_color?: string
}

export interface EventUpdateRequest {
  title?: string
  title_ar?: string
  description?: string
  event_type_id?: string
  category_id?: string
  start_date?: string
  end_date?: string
  timezone?: string
  venue_name?: string
  venue_name_ar?: string
  venue_address?: string
  venue_city?: string
  venue_country?: string
  venue_map_url?: string
  venue_lat?: number
  venue_lng?: number
  vip_quota?: number
  normal_quota?: number
  capacity?: number
  vip_capacity?: number
  normal_capacity?: number
  allow_rsvp?: boolean
  allow_plus_one?: boolean
  allow_reentry?: boolean
  require_name?: boolean
  cover_image_url?: string
  theme_color?: string
  team_id?: string
}

export interface EventGate {
  id: string
  event_id: string
  name: string
  name_ar: string | null
  allowed_classes: TicketClass[] | null
  is_active: boolean
  created_at: string
  team_id?: string | null
  assigned_users?: string[]
}

export interface EventGateCreate {
  name: string
  name_ar?: string
  allowed_classes?: TicketClass[]
  team_id?: string | null
  assigned_users?: string[]
}

export interface EventStats {
  vip_quota_used?: number;
  normal_quota_used?: number;
  total_invitations: number
  vip_count: number
  normal_count: number
  sent_count: number
  viewed_count: number
  accepted_count: number
  declined_count: number
  checked_in_count: number
  revoked_count: number
}

export interface EventAsset {
  id: string
  event_id: string
  asset_type: string
  file_url: string
  file_name: string | null
  mime_type: string | null
  size: number
  metadata: Record<string, any> | null
  sort_order: number
  created_at: string
}

export interface EventAssetCreate {
  event_id: string
  asset_type: string
  file_url: string
  file_name?: string
  mime_type?: string
  size?: number
  metadata?: Record<string, any>
  sort_order?: number
}

export interface EventStatusTransitionRequest {
  new_status: EventStatus
}
