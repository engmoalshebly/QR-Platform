import http from '@services/http/client'

export type OperationStatus =
  | 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancel_requested' | 'cancelled'

export const TERMINAL_STATUSES: readonly OperationStatus[] = ['completed', 'partial', 'failed', 'cancelled']

export interface GenerationCapabilities {
  contract_version: number
  enabled: boolean
  max_cards: number
  max_people_per_card: number
  output_formats: Array<'pdf' | 'zip'>
}

export interface GenerationOperation {
  id: string
  event_id: string
  mode: 'quick' | 'designed'
  source: 'count' | 'names' | 'excel'
  status: OperationStatus
  cards_count: number
  people_count: number
  vip_cards: number
  normal_cards: number
  vip_people: number
  normal_people: number
  cards_done: number
  cards_failed: number
  files_done: number
  files_failed: number
  files_expected: number
  created_at: string
  updated_at: string
  completed_at: string | null
  error_code: string | null
  error_message: string | null
  replayed: boolean
  status_url: string
}

export interface GenerationArtifact {
  id: string
  batch_id: string
  kind: 'pdf' | 'zip'
  part_index: number
  file_part: number | null
  byte_size: number
  cards_count: number
  verified_at: string | null
}

export interface Page<T> { items: T[]; next_cursor: string | null }

export interface CreateOperationPayload {
  contract_version: 1
  event_id: string
  mode: 'quick' | 'designed'
  source: 'count' | 'names' | 'excel'
  rows?: Array<Record<string, unknown>>
  count?: { vip_count: number; normal_count: number; guest_name_prefix: string }
  templates?: Partial<Record<'vip' | 'normal', string>>
  layout?: Record<string, unknown>
  output_formats: Array<'pdf' | 'zip'>
  require_rsvp: boolean
  original_filename?: string
}

const base = '/generation-operations'

export const generationOperationsApi = {
  capabilities: () => http.get<GenerationCapabilities>(`${base}/capabilities`).then((r) => r.data),

  create: (payload: CreateOperationPayload, idempotencyKey: string) =>
    http.post<GenerationOperation>(base, payload, { headers: { 'Idempotency-Key': idempotencyKey } }).then((r) => r.data),

  get: (id: string) => http.get<GenerationOperation>(`${base}/${id}`).then((r) => r.data),

  // `status` repeats (status=a&status=b), which is what FastAPI expects for list queries.
  list: (eventId: string, before?: string, limit = 25, status?: OperationStatus[]) =>
    http.get<Page<GenerationOperation>>(base, {
      params: { event_id: eventId, before, limit, status },
      paramsSerializer: { indexes: null },
    }).then((r) => r.data),

  artifacts: (id: string, before?: string) =>
    http.get<Page<GenerationArtifact>>(`${base}/${id}/artifacts`, { params: { before, limit: 100 } }).then((r) => r.data),

  cancel: (id: string) => http.post<GenerationOperation>(`${base}/${id}/cancel`).then((r) => r.data),

  retry: (id: string) => http.post<GenerationOperation>(`${base}/${id}/retry`).then((r) => r.data),

  artifactDownloadPath: (id: string, artifactId: string) => `${base}/${id}/artifacts/${artifactId}/download`,
}

/**
 * One stable Idempotency-Key per distinct request body. A lost response is retried with the
 * same key (server replays the operation); a changed body gets a new key. Cleared on success.
 */
const pendingKeys = new Map<string, string>()

const newKey = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto
  ? crypto.randomUUID()
  : `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`)

export async function submitOperation(payload: CreateOperationPayload, scope: string) {
  const fingerprint = `${scope}:${JSON.stringify(payload)}`
  let key = pendingKeys.get(fingerprint)
  if (!key) {
    key = newKey()
    pendingKeys.set(fingerprint, key)
  }
  const operation = await generationOperationsApi.create(payload, key)
  pendingKeys.delete(fingerprint)
  return operation
}

/** Release a key when the server definitively rejected the request (4xx other than 409/429). */
export function discardPendingKeys() { pendingKeys.clear() }
