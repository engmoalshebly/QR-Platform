import { useCallback, useRef, useState } from 'react'
import { getApiErrorMessage } from '@services/http/client'
import { generationImportsApi, type ImportSummary, type ImportUpload } from '../api/generationImportsApi'
import type { GenerationOperation } from '../api/generationOperationsApi'

const key = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`)

export interface ServerImportState {
  upload: ImportUpload | null
  fileName: string
  sheet: string | null
  delimiter: ',' | ';' | '\t'
  mapping: Record<string, string>
  revision: number
  analyzedRsvp: boolean
  summary: ImportSummary | null
  /** Valid rows the user unticked; the server selects every other valid row. */
  deselected: number[]
  acknowledged: boolean
  selectionReady: boolean
  operation: GenerationOperation | null
  busy: boolean
  error: string | null
}

const initial: ServerImportState = {
  upload: null, fileName: '', sheet: null, delimiter: ',', mapping: {}, revision: 0, analyzedRsvp: false, summary: null,
  deselected: [], acknowledged: false, selectionReady: false, operation: null, busy: false, error: null,
}

/**
 * Server-side import draft: the browser never holds the rows. Any change to file, sheet,
 * mapping or RSVP invalidates the previous validation and selection, as the server enforces.
 */
export function useServerImport(eventId: string, requireRsvp: boolean) {
  const [s, setS] = useState<ServerImportState>(initial)
  const generateKey = useRef<{ fingerprint: string; key: string } | null>(null)
  const patch = (p: Partial<ServerImportState>) => setS((prev) => ({ ...prev, ...p }))

  const run = useCallback(async (work: () => Promise<Partial<ServerImportState>>) => {
    setS((prev) => ({ ...prev, busy: true, error: null }))
    try { const result = await work(); setS((prev) => ({ ...prev, ...result, busy: false })) }
    catch (e) { setS((prev) => ({ ...prev, busy: false, error: getApiErrorMessage(e, 'تعذر إكمال العملية. أعد المحاولة.') })) }
  }, [])

  const analyze = (over: Partial<Pick<ServerImportState, 'sheet' | 'delimiter' | 'mapping'>> = {}, upload = s.upload, revision = s.revision) =>
    run(async () => {
      if (!upload) return {}
      const next = { sheet: s.sheet, delimiter: s.delimiter, mapping: s.mapping, ...over }
      const summary = await generationImportsApi.analyze(upload.id, {
        revision, sheet: next.sheet, delimiter: next.delimiter, mapping: next.mapping, require_rsvp: requireRsvp,
      })
      // Default selection: every valid row. Excluded rows then need explicit acknowledgement.
      return { ...next, summary, revision: summary.revision, analyzedRsvp: requireRsvp, selectionReady: false, acknowledged: false, deselected: [] }
    })

  const chooseFile = (file: File) =>
    run(async () => {
      generateKey.current = null
      const upload = await generationImportsApi.upload(eventId, file)
      const sheet = upload.sheets[0] ?? null
      const summary = await generationImportsApi.analyze(upload.id, {
        revision: upload.revision, sheet, delimiter: ',', mapping: {}, require_rsvp: requireRsvp,
      })
      return { ...initial, upload, fileName: file.name, sheet, summary, revision: summary.revision, analyzedRsvp: requireRsvp }
    })

  const confirmSelection = (acknowledge: boolean, rowNumbers?: number[]) =>
    run(async () => {
      if (!s.upload) return {}
      const summary = await generationImportsApi.select(s.upload.id, s.revision, acknowledge, rowNumbers, s.deselected)
      return { summary, revision: summary.revision, acknowledged: acknowledge, selectionReady: true }
    })

  const generate = (opts: { layout?: Record<string, unknown>; formats: Array<'pdf' | 'zip'>; mode?: 'quick' | 'designed'; templates?: Partial<Record<'vip' | 'normal', string>> }) =>
    run(async () => {
      if (!s.upload) return {}
      const body = { source_revision: s.revision, mode: opts.mode ?? ('quick' as const), ...(opts.mode === 'designed' ? { templates: opts.templates } : {}), layout: opts.layout, output_formats: opts.formats, require_rsvp: requireRsvp }
      const fingerprint = JSON.stringify([s.upload.id, body])
      if (generateKey.current?.fingerprint !== fingerprint) generateKey.current = { fingerprint, key: key() }
      const operation = await generationImportsApi.generate(s.upload.id, body, generateKey.current.key)
      return { operation }
    })

  // Changing the selection invalidates a confirmed one: the server revision moves on confirm only.
  const toggleRow = (row: number) => setS((prev) => ({
    ...prev, selectionReady: false, acknowledged: false,
    deselected: prev.deselected.includes(row) ? prev.deselected.filter((n) => n !== row) : [...prev.deselected, row],
  }))
  const selectAllRows = () => setS((prev) => ({ ...prev, deselected: [], selectionReady: false, acknowledged: false }))

  const reset = () => { generateKey.current = null; setS(initial) }

  return { state: s, patch, chooseFile, analyze, confirmSelection, generate, toggleRow, selectAllRows, reset }
}
export type ServerImport = ReturnType<typeof useServerImport>
