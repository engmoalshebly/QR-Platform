import { useAuthStore } from '@features/auth/store/authStore'

/** Persist only an opaque request digest and key, never guest data. Fail before POST
 * when the browser cannot retain identity: an ambiguous response must be retryable. */
export async function generationRequestKey(scope: string, body: unknown) {
  const userId = useAuthStore.getState().user?.id
  if (!userId) throw new Error('انتهت الجلسة. سجّل الدخول قبل إنشاء الدعوات.')
  // JSONB restores object keys in a different order. Canonicalize objects so
  // the same restored draft keeps its key; array/guest order remains meaningful.
  const canonical = JSON.stringify([userId, scope, body], (_key, value: unknown) => {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
    }
    return value
  })
  const bytes = new TextEncoder().encode(canonical)
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('')
  const storageKey = `generation-request:${digest}`
  let value: string | null
  try {
    value = sessionStorage.getItem(storageKey)
    if (!value) {
      value = crypto.randomUUID()
      sessionStorage.setItem(storageKey, value)
    }
  } catch {
    throw new Error('تعذر حفظ هوية الطلب بأمان. اسمح بتخزين الجلسة ثم أعد المحاولة.')
  }
  return { key: value, complete: () => { sessionStorage.removeItem(storageKey) } }
}
