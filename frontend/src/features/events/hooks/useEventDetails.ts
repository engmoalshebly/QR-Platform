/**
 * useEventDetails.ts
 * React Query hooks for the Event Details page.
 * All mutations invalidate BOTH the list and the detail cache.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { eventsAPI, eventKeys } from '../api/eventsApi'
import type { EventGateCreate, EventUpdateRequest } from '../types'

// ── Detail ──────────────────────────────────────────────────────
/** Warm an event page before it is opened (hover/focus on a list item). */
export function usePrefetchEvent(tenantId: string | null) {
  const queryClient = useQueryClient()
  return (eventId: string) => {
    if (!tenantId) return
    void import('../pages/EventDetailsPage')
    void queryClient.prefetchQuery({ queryKey: eventKeys.detail(tenantId, eventId), queryFn: () => eventsAPI.get(eventId), staleTime: 10_000 })
    void queryClient.prefetchQuery({ queryKey: eventKeys.stats(eventId), queryFn: () => eventsAPI.stats(eventId), staleTime: 10_000 })
  }
}

export function useEventDetail(tenantId: string | null, eventId: string | undefined) {
  return useQuery({
    queryKey: eventKeys.detail(tenantId ?? '', eventId ?? ''),
    queryFn: () => eventsAPI.get(eventId!),
    enabled: Boolean(tenantId && eventId),
    staleTime: 10_000,
  })
}

// ── Stats ───────────────────────────────────────────────────────
export function useEventStats(eventId: string | undefined) {
  return useQuery({
    queryKey: eventKeys.stats(eventId ?? ''),
    queryFn: () => eventsAPI.stats(eventId!),
    enabled: Boolean(eventId),
    refetchInterval: 30_000, // live refresh every 30s
  })
}

// ── Gates ───────────────────────────────────────────────────────
export function useEventGates(eventId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: eventKeys.gates(eventId ?? ''),
    queryFn: () => eventsAPI.gates(eventId!),
    enabled: Boolean(eventId) && enabled,
    staleTime: 10_000,
  })
}

// ── Update ──────────────────────────────────────────────────────
export function useEventUpdate(tenantId: string | null, eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: EventUpdateRequest) => eventsAPI.update(eventId!, data),
    onSuccess: (updatedEvent) => {
      // Update both list and detail in cache
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
      queryClient.setQueryData(
        eventKeys.detail(tenantId ?? '', eventId ?? ''),
        updatedEvent,
      )
    },
  })
}

// ── Upload Cover ────────────────────────────────────────────────
export function useEventCoverUpload(tenantId: string | null, eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (file: File) => eventsAPI.uploadCover(eventId!, file),
    onSuccess: () => {
      // Invalidate/refresh both list and detail in cache
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(tenantId ?? '', eventId ?? '') })
    },
  })
}

// ── Publish ─────────────────────────────────────────────────────
export function useEventPublish(tenantId: string | null, eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => eventsAPI.publish(eventId!),
    onSuccess: (publishedEvent) => {
      // Sync both list and detail immediately without a round-trip
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
      queryClient.setQueryData(
        eventKeys.detail(tenantId ?? '', eventId ?? ''),
        publishedEvent,
      )
      // Refresh stats after publish
      queryClient.invalidateQueries({ queryKey: eventKeys.stats(eventId ?? '') })
    },
  })
}

// ── Create Gate ─────────────────────────────────────────────────
export function useGateCreate(eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: EventGateCreate) => eventsAPI.createGate(eventId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.gates(eventId ?? '') })
    },
  })
}

// ── Update Gate ─────────────────────────────────────────────────
export function useGateUpdate(eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ gateId, data }: { gateId: string; data: EventGateCreate }) =>
      eventsAPI.updateGate(eventId!, gateId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.gates(eventId ?? '') })
    },
  })
}

// ── Delete Gate ─────────────────────────────────────────────────
export function useGateDelete(eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (gateId: string) => eventsAPI.deleteGate(eventId!, gateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.gates(eventId ?? '') })
    },
  })
}

// ── Delete Event ────────────────────────────────────────────────
export function useEventDelete(tenantId: string | null, eventId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => eventsAPI.delete(eventId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: eventKeys.all(tenantId ?? '') })
    },
  })
}
