/**
 * useEvents.ts
 * React Query hooks for the Events list page.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { eventsAPI, eventKeys } from '../api/eventsApi'
import type { EventCreateRequest, EventStatus } from '../types'

// ── List ────────────────────────────────────────────────────────
export function useEventsList(
  tenantId: string | null,
  statusFilter: EventStatus | '',
  enabled = true,
) {
  return useQuery({
    queryKey: eventKeys.list(tenantId ?? '', statusFilter),
    queryFn: () => eventsAPI.list(statusFilter || undefined),
    enabled: Boolean(tenantId) && enabled,
    staleTime: 30_000, // 30s — avoid unnecessary refetches
  })
}

// ── Create ──────────────────────────────────────────────────────
export function useEventCreate(tenantId: string | null) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  return useMutation({
    mutationFn: (data: EventCreateRequest) => eventsAPI.create(data),
    onSuccess: (newEvent) => {
      // Invalidate the full tenant event list
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
      navigate(`/events/${newEvent.id}`)
    },
  })
}

// ── Delete ──────────────────────────────────────────────────────
export function useEventDelete(tenantId: string | null) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (eventId: string) => eventsAPI.delete(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
    },
  })
}
