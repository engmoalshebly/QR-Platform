import http from '@services/http/client'
import type { GenerationOperation } from './generationOperationsApi'

export interface ImportSummary {
  total: number; valid: number; invalid: number; blank: number
  selected: number; vip: number; normal: number; people: number
  selected_people?: number; selected_vip?: number; selected_normal?: number; excluded?: number
}
export interface ImportUpload { id: string; revision: number; status: string; sheets: string[]; byte_size: number; sha256: string }
export interface ImportRow {
  row_number: number
  raw_data: Record<string, unknown>
  normalized_data: { guest_name: string; ticket_class: 'vip' | 'normal'; guest_count: number } | null
  errors: string[]
  excluded: boolean
  selected: boolean
}
export type RowState = 'all' | 'valid' | 'invalid' | 'selected' | 'excluded'
export interface AnalyzeBody {
  revision: number; sheet?: string | null; delimiter: ',' | ';' | '\t'
  mapping: Record<string, string>; require_rsvp: boolean
}

const base = '/generation-imports'
const mimeFor = (name: string) =>
  name.toLowerCase().endsWith('.csv') ? 'text/csv' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export const generationImportsApi = {
  upload: (eventId: string, file: File) =>
    http.post<ImportUpload>(base, file, { params: { event_id: eventId, filename: file.name }, headers: { 'Content-Type': mimeFor(file.name) } }).then((r) => r.data),

  analyze: (id: string, body: AnalyzeBody) =>
    http.post<ImportSummary & { revision: number }>(`${base}/${id}/analyze`, body).then((r) => r.data),

  select: (id: string, revision: number, acknowledge: boolean, rowNumbers?: number[], exclude?: number[]) =>
    http.post<ImportSummary & { revision: number }>(`${base}/${id}/selection`, {
      revision, acknowledge_exclusions: acknowledge, ...(rowNumbers ? { row_numbers: rowNumbers } : {}),
      ...(exclude && exclude.length ? { exclude_row_numbers: exclude } : {}),
    }).then((r) => r.data),

  rows: (id: string, p: { after?: number; state: RowState; search?: string; ticket_class?: 'vip' | 'normal' }) =>
    http.get<{ items: ImportRow[]; next_row: number | null }>(`${base}/${id}/rows`, {
      params: { after: p.after ?? 0, limit: 50, state: p.state, search: p.search || undefined, ticket_class: p.ticket_class },
    }).then((r) => r.data),

  errorsPath: (id: string) => `${base}/${id}/errors.csv`,

  generate: (id: string, body: { source_revision: number; mode: 'quick' | 'designed'; templates?: Partial<Record<'vip' | 'normal', string>>; layout?: Record<string, unknown>; output_formats: Array<'pdf' | 'zip'>; require_rsvp: boolean }, key: string) =>
    http.post<GenerationOperation>(`${base}/${id}/generate`, body, { headers: { 'Idempotency-Key': key } }).then((r) => r.data),
}
