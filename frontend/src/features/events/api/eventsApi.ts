/**
 * eventsApi.ts
 * Centralised API layer for the Events feature.
 * Includes typed query keys so all mutations invalidate consistently.
 */
import http from '@services/http/client'
import type {
  EventModel,
  EventCreateRequest,
  EventUpdateRequest,
  EventCategory,
  EventType,
  EventGate,
  EventGateCreate,
  EventStats,
  EventStatusTransitionRequest,
  EventAsset,
  EventAssetCreate,
  EventStatus,
} from '../types'

// ── Query Key Factory ──────────────────────────────────────────
// Single place to define keys — prevents cache invalidation bugs.
export const eventKeys = {
  /** All events for a tenant (parent key) */
  all: (tenantId: string) => ['events', tenantId] as const,
  /** Paginated / filtered list */
  list: (tenantId: string, status?: EventStatus | '') =>
    ['events', tenantId, 'list', status ?? ''] as const,
  /** Single event detail */
  detail: (tenantId: string, eventId: string) =>
    ['events', tenantId, 'detail', eventId] as const,
  /** Stats for an event */
  stats: (eventId: string) => ['event-stats', eventId] as const,
  /** Gates for an event */
  gates: (eventId: string) => ['event-gates', eventId] as const,
  /** Assets for an event */
  assets: (eventId: string) => ['event-assets', eventId] as const,
}

// ── API Functions ───────────────────────────────────────────────
export const eventsAPI = {
  // Lookup data
  categories: () =>
    http.get<EventCategory[]>('/events/categories').then((r) => r.data),
  types: (categoryId?: string) =>
    http
      .get<EventType[]>('/events/types', { params: { category_id: categoryId } })
      .then((r) => r.data),

  // Events CRUD
  list: (status?: EventStatus | '') =>
    http
      .get<EventModel[]>('/events', { params: status ? { status } : undefined })
      .then((r) => r.data),
  get: (eventId: string) =>
    http.get<EventModel>(`/events/${eventId}`).then((r) => r.data),
  create: (data: EventCreateRequest) =>
    http.post<EventModel>('/events', data).then((r) => r.data),
  update: (eventId: string, data: EventUpdateRequest) =>
    http.patch<EventModel>(`/events/${eventId}`, data).then((r) => r.data),
  uploadCover: (eventId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<{ cover_image_url: string }>(`/events/${eventId}/cover`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }).then((r) => r.data)
  },
  getLogo: (eventId: string) =>
    http.get<{ logo_url: string | null }>(`/events/${eventId}/logo`).then((r) => r.data),
  uploadLogo: (eventId: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return http.post<{ asset_id: string; logo_url: string }>(`/events/${eventId}/logo`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then((r) => r.data)
  },
  delete: (eventId: string) =>
    http.delete(`/events/${eventId}`).then((r) => r.data),
  publish: (eventId: string) =>
    http.post<EventModel>(`/events/${eventId}/publish`).then((r) => r.data),
  transition: (eventId: string, data: EventStatusTransitionRequest) =>
    http
      .post<EventModel>(`/events/${eventId}/transition`, data)
      .then((r) => r.data),

  // Stats
  stats: (eventId: string) =>
    http.get<EventStats>(`/events/${eventId}/stats`).then((r) => r.data),

  // Gates
  gates: (eventId: string) =>
    http.get<EventGate[]>(`/events/${eventId}/gates`).then((r) => r.data),
  createGate: (eventId: string, data: EventGateCreate) =>
    http.post<EventGate>(`/events/${eventId}/gates`, data).then((r) => r.data),
  updateGate: (eventId: string, gateId: string, data: EventGateCreate) =>
    http.put<EventGate>(`/events/${eventId}/gates/${gateId}`, data).then((r) => r.data),
  deleteGate: (eventId: string, gateId: string) =>
    http.delete(`/events/${eventId}/gates/${gateId}`).then((r) => r.data),

  // Assets
  assets: (eventId: string) =>
    http.get<EventAsset[]>(`/events/${eventId}/assets`).then((r) => r.data),
  createAsset: (eventId: string, data: EventAssetCreate) =>
    http
      .post<EventAsset>(`/events/${eventId}/assets`, data)
      .then((r) => r.data),
  deleteAsset: (eventId: string, assetId: string) =>
    http.delete(`/events/${eventId}/assets/${assetId}`).then((r) => r.data),
}
