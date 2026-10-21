import { useEffect, useRef, useState } from 'react'
import http, { getApiErrorMessage } from '@services/http/client'
import type { GuestImportRow } from '../components/invitations/types'

/** Bounded server draft; no names, phone numbers or emails in browser storage. */
export function useGenerationDraftRows(eventId: string, kind: 'quick' | 'designed', enabled: boolean) {
  const [rows, setRows] = useState<GuestImportRow[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const revision = useRef(0)
  const saved = useRef('[]')
  const saving = useRef(false)
  const latest = useRef('[]')
  const path = `/generation-drafts/${eventId}/${kind}`
  const legacyKey = `event-invitations-${kind === 'quick' ? 'quick' : 'design'}-manual:${eventId}`
  const [legacyAvailable, setLegacyAvailable] = useState(() => {
    try { return sessionStorage !== undefined && localStorage.getItem(legacyKey) !== null } catch { return false }
  })
  const restoreLegacy = async () => {
    if (!ready || saving.current || rows.length) {
      setError('احتفظ بالمسودة الحالية أولاً؛ استعادة المسودة السابقة متاحة إلى قائمة فارغة فقط.')
      return
    }
    saving.current = true
    try {
      const legacy: unknown = JSON.parse(localStorage.getItem(legacyKey) || '[]')
      if (!Array.isArray(legacy) || legacy.length > 1000 || legacy.some(row => !row || typeof row.guest_name !== 'string' || (row.custom_fields != null && typeof row.custom_fields !== 'object'))) {
        throw new Error('المسودة السابقة غير صالحة. لم يتم حذفها أو استبدال المسودة الخادمية.')
      }
      const normalized = legacy.map(row => ({ ...row, invitation_count: row.invitation_count ?? 1, ticket_class: row.ticket_class ?? 'normal', custom_fields: row.custom_fields ?? {} }))
      const { data } = await http.put<{ revision: number }>(path, { revision: revision.current, rows: normalized })
      revision.current = data.revision
      saved.current = JSON.stringify(normalized)
      latest.current = saved.current
      setRows(normalized)
      setError(null)
      localStorage.removeItem(legacyKey)
      setLegacyAvailable(false)
    } catch (e) { setError(getApiErrorMessage(e, 'تعذر نقل المسودة السابقة؛ بقيت محفوظة محلياً')) }
    finally { saving.current = false; setTick(n => n + 1) }
  }
  useEffect(() => {
    if (!enabled) return
    let active = true
    void http.get<{ rows: GuestImportRow[]; revision: number }>(path).then(({ data }) => {
      if (!active) return
      revision.current = data.revision
      saved.current = JSON.stringify(data.rows)
      latest.current = saved.current
      setRows(data.rows)
      setReady(true)
    }).catch(e => { if (active) setError(getApiErrorMessage(e, 'تعذر استعادة المسودة')) })
    return () => { active = false }
  }, [enabled, path])
  const serialized = JSON.stringify(rows)
  if (ready) latest.current = serialized
  useEffect(() => {
    if (!enabled || !ready || error || saving.current || latest.current === saved.current) return
    saving.current = true
    // Drain edits made while a save is in flight, even after leaving this tab.
    // Each closure retains its owner's event path and revision.
    void (async () => {
      try {
        while (latest.current !== saved.current) {
          const payload = latest.current
          const { data } = await http.put<{ revision: number }>(path, { revision: revision.current, rows: JSON.parse(payload) })
          revision.current = data.revision
          saved.current = payload
        }
      } catch (e) {
        setError(getApiErrorMessage(e, 'تعذر حفظ المسودة؛ احتفظ بالصفحة مفتوحة'))
      } finally {
        saving.current = false
        setTick(n => n + 1)
      }
    })()
  }, [enabled, ready, error, serialized, path, tick])
  useEffect(() => {
    if (!enabled || serialized === saved.current) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [enabled, serialized, tick])
  return { rows, setRows, ready, legacyAvailable: ready && legacyAvailable, restoreLegacy, retry: () => { setError(null); setTick(n => n + 1) },
    loading: enabled && !ready && !error, error,
    saving: enabled && ready && serialized !== saved.current && !error }
}
