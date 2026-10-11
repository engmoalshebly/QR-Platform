export type LimitErrorCode =
  | 'PLAN_LIMIT_EXCEEDED'
  | 'EVENT_QUOTA_EXCEEDED'
  | 'FEATURE_NOT_INCLUDED'
  | 'FEATURE_DISABLED'
  | 'RATE_LIMIT_EXCEEDED'
  | 'PLAN_LIMIT_NOT_CONFIGURED'
  | 'USAGE_BUSY'

/** Structured metadata stays available to callers independently of UI text. */
export const getApiErrorCode = (error: unknown): LimitErrorCode | undefined => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (!detail || typeof detail !== 'object' || !('code' in detail)) return undefined
  const codes: readonly unknown[] = [
    'PLAN_LIMIT_EXCEEDED', 'EVENT_QUOTA_EXCEEDED', 'FEATURE_NOT_INCLUDED',
    'FEATURE_DISABLED', 'RATE_LIMIT_EXCEEDED', 'PLAN_LIMIT_NOT_CONFIGURED', 'USAGE_BUSY',
  ]
  return codes.includes(detail.code) ? detail.code as LimitErrorCode : undefined
}

/** Convert FastAPI's string or structured `detail` payload into readable UI text. */
export const getApiErrorMessage = (error: unknown, fallback = 'تعذر إكمال الطلب') => {
  const candidate = error as {
    response?: { data?: { detail?: unknown } }
    message?: unknown
  }
  const detail = candidate?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    const payload = detail as { message?: unknown; issues?: unknown; fields?: unknown }
    const message = typeof payload.message === 'string' ? payload.message.trim() : ''
    const issues = Array.isArray(payload.issues)
      ? payload.issues.filter((issue): issue is string => typeof issue === 'string' && Boolean(issue.trim()))
      : []
    const fields = Array.isArray(payload.fields)
      ? payload.fields.filter((field): field is string => typeof field === 'string' && Boolean(field.trim()))
      : []
    const details = [...issues, ...fields]
    if (message || details.length) {
      return [message, ...details.map((item) => `• ${item}`)].filter(Boolean).join('\n')
    }
  }

  return typeof candidate?.message === 'string' && candidate.message.trim()
    ? candidate.message
    : fallback
}

