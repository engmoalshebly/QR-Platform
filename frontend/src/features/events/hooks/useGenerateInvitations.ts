import { useMutation, useQueryClient } from '@tanstack/react-query'
import { invitationsApi, FastInvitationRequest, FastGenerationResponse } from '../api/invitationsApi'
import {
  generationOperationsApi,
  submitOperation,
  type CreateOperationPayload,
  type GenerationOperation,
} from '../api/generationOperationsApi'
import { useAuthStore } from '@features/auth/store/authStore'

export interface GenerateVariables extends FastInvitationRequest {
  /** How the guests were entered; "count" lets the server create names without sending rows. */
  source_kind?: 'count' | 'names' | 'excel'
  count?: { vip_count: number; normal_count: number; guest_name_prefix: string }
  original_filename?: string
}

/** `operation` is set on the durable 202 contract: accepted, not finished. */
export type GenerateResult = FastGenerationResponse & { operation?: GenerationOperation }

export function toOperationPayload(v: GenerateVariables): CreateOperationPayload {
  const formats: Array<'pdf' | 'zip'> = []
  if (v.generate_pdf) formats.push('pdf')
  if (v.generate_zip) formats.push('zip')
  const base = {
    contract_version: 1 as const,
    event_id: v.event_id,
    mode: 'quick' as const,
    layout: v.layout_config as Record<string, unknown> | undefined,
    output_formats: formats,
  }
  const rsvp = v.invitations.some((i) => i.metadata?.require_rsvp === true)
  if (v.source_kind === 'count' && v.count && !rsvp) {
    return { ...base, source: 'count', count: v.count, require_rsvp: false }
  }
  return {
    ...base,
    source: v.source_kind === 'excel' ? 'excel' : 'names',
    rows: v.invitations,
    require_rsvp: rsvp,
    original_filename: v.original_filename,
  }
}

const isContractUpgrade = (error: unknown) =>
  (error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code === 'GENERATION_CONTRACT_UPGRADE'

export const useGenerateInvitations = () => {
  const queryClient = useQueryClient()
  const tenantId = useAuthStore((s) => s.currentTenantId)

  const viaOperations = async (data: GenerateVariables): Promise<GenerateResult> => {
    const operation = await submitOperation(toOperationPayload(data), String(tenantId))
    return { success: false, total_invitations: operation.cards_count, generation_time_ms: 0, operation }
  }

  return useMutation<GenerateResult, Error, GenerateVariables>({
    mutationFn: async (data) => {
      const caps = await queryClient.fetchQuery({
        queryKey: ['generation-capabilities', tenantId],
        queryFn: generationOperationsApi.capabilities,
        staleTime: 5 * 60_000,
      }).catch(() => null)
      if (caps?.enabled) return viaOperations(data)
      const { source_kind, count, original_filename, ...legacy } = data
      void source_kind; void count; void original_filename
      try {
        return await invitationsApi.generateFast(legacy)
      } catch (error) {
        // The server switched contracts after this tab loaded; re-read and retry once.
        if (isContractUpgrade(error)) {
          await queryClient.invalidateQueries({ queryKey: ['generation-capabilities', tenantId] })
          return viaOperations(data)
        }
        throw error
      }
    },
    onSuccess: (_res, variables) => {
      queryClient.invalidateQueries({ queryKey: ['event-stats', variables.event_id] })
      queryClient.invalidateQueries({ queryKey: ['events', tenantId, 'detail', variables.event_id] })
      queryClient.invalidateQueries({ queryKey: ['fast-generation-history', variables.event_id] })
      queryClient.invalidateQueries({ queryKey: ['generation-operations', tenantId, variables.event_id] })
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
    },
  })
}
