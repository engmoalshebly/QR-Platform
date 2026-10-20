import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@features/auth/store/authStore'
import {
  generationOperationsApi,
  TERMINAL_STATUSES,
  type GenerationOperation,
} from '../api/generationOperationsApi'

/** Whether the durable 202 contract is on. Failing closed keeps the legacy path working. */
export function useGenerationCapabilities() {
  const tenantId = useAuthStore((s) => s.currentTenantId)
  return useQuery({
    queryKey: ['generation-capabilities', tenantId],
    queryFn: generationOperationsApi.capabilities,
    enabled: !!tenantId,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

const usePageVisible = () => {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || !document.hidden)
  useEffect(() => {
    const onChange = () => setVisible(!document.hidden)
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [])
  return visible
}

/** 2s while running, backing off to 30s; stops on a final state or a hidden page. */
export const pollDelay = (operation: GenerationOperation | undefined, failures: number) => {
  if (operation && TERMINAL_STATUSES.includes(operation.status)) return false
  const base = operation?.status === 'queued' ? 4000 : 2000
  return Math.min(30_000, base * 2 ** Math.min(failures, 4))
}

export function useGenerationOperation(operationId: string | null | undefined) {
  const queryClient = useQueryClient()
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const visible = usePageVisible()
  const key = ['generation-operation', tenantId, operationId]

  const query = useQuery({
    queryKey: key,
    queryFn: () => generationOperationsApi.get(operationId as string),
    enabled: !!operationId && !!tenantId,
    refetchInterval: (q) => (visible ? pollDelay(q.state.data, q.state.fetchFailureCount) : false),
    refetchOnWindowFocus: true,
    retry: false,
  })

  const terminal = !!query.data && TERMINAL_STATUSES.includes(query.data.status)
  useEffect(() => {
    if (!terminal || !query.data) return
    queryClient.invalidateQueries({ queryKey: ['generation-operations', tenantId, query.data.event_id] })
    queryClient.invalidateQueries({ queryKey: ['event-stats', query.data.event_id] })
    queryClient.invalidateQueries({ queryKey: ['invitations'] })
  }, [terminal, query.data?.id, query.data?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  return query
}
