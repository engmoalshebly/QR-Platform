import { useAuthStore } from '@features/auth/store/authStore'

/** Persist only an opaque request digest and key, never guest data. Fail before POST
 * when the browser cannot retain identity: an ambiguous response must be retryable. */
export async function generationRequestKey(scope: string, body: unknown) {
  const userId = useAuthStore.getState().user?.id
  if (!userId) throw new Error('انتهت الجلسة. سجّل الدخول قبل إنشاء الدعوات.')
  const bytes = new TextEncoder().encode(JSON.stringify([userId, scope, body]))
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
