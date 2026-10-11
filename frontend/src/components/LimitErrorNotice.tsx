import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { usePermission, PERM } from '@shared/permissions'
import { getApiErrorCode, getApiErrorMessage } from '@services/http/client'
import { PricingModal } from '@features/dashboard/components/PricingModal'
import { useAuthStore } from '@features/auth/store/authStore'
import './limit-error-notice.css'

interface Props { error: unknown; onRetry?: () => void; busy?: boolean }

export function LimitErrorNotice({ error, onRetry, busy = false }: Props) {
  const code = getApiErrorCode(error)
  // Both ask the user to wait a few seconds and retry; neither is a plan problem.
  const waiting = code === 'RATE_LIMIT_EXCEEDED' || code === 'USAGE_BUSY'
  const currentPlanCode = useAuthStore(s => s.tenants.find(t => t.tenant_id === s.currentTenantId)?.plan || 'starter')
  const canManageBilling = usePermission(PERM.BILLING_MANAGE)
  const canEditEvent = usePermission(PERM.EVENT_TAB_SETTINGS)
  const [showPlans, setShowPlans] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const detail = (error as { response?: { data?: { detail?: Record<string, unknown> } } })?.response?.data?.detail
  useEffect(() => {
    if (!waiting) { setSeconds(0); return }
    const header = (error as { response?: { headers?: Record<string, unknown> } })?.response?.headers?.['retry-after']
    const duration = Number(detail?.retry_after ?? header ?? 60)
    const end = Date.now() + (Number.isFinite(duration) ? Math.max(1, duration) : 60) * 1000
    const tick = () => setSeconds(Math.max(0, Math.ceil((end - Date.now()) / 1000)))
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [error, waiting, detail?.retry_after])
  if (!error) return null
  const numeric = (key: string) => typeof detail?.[key] === 'number' ? detail[key] as number : undefined
  const current = numeric('current'), limit = numeric('limit'), requested = numeric('requested')
  const reset = typeof detail?.resets_at === 'string' ? new Date(detail.resets_at) : null
  const eventId = typeof detail?.event_id === 'string' ? detail.event_id : null
  const upgrade = code === 'PLAN_LIMIT_EXCEEDED' || code === 'FEATURE_NOT_INCLUDED'
  return <>
    <div className="limit-error-notice" role="alert" dir="rtl">
      <p>{typeof error === 'string' ? error : getApiErrorMessage(error)}</p>
      {current !== undefined && limit !== undefined && requested !== undefined && <dl>
        <div><dt>المستخدم</dt><dd>{current.toLocaleString('ar')}</dd></div>
        <div><dt>المتاح</dt><dd>{Math.max(0, limit - current).toLocaleString('ar')}</dd></div>
        <div><dt>المطلوب</dt><dd>{requested.toLocaleString('ar')}</dd></div>
      </dl>}
      {reset && !Number.isNaN(reset.getTime()) && <p>يتجدد الرصيد في {new Intl.DateTimeFormat('ar', { dateStyle: 'medium', timeStyle: 'short' }).format(reset)} حسب توقيت جهازك.</p>}
      {upgrade && (canManageBilling
        ? <button type="button" onClick={() => setShowPlans(true)}>عرض الباقات</button>
        : <p>تواصل مع مسؤول الحساب لإدارة الاشتراك أو السعة المتاحة.</p>)}
      {code === 'EVENT_QUOTA_EXCEEDED' && (canEditEvent && eventId
        ? <a href={`/events/${encodeURIComponent(eventId)}?tab=overview`} target="_blank" rel="noopener noreferrer">إدارة حصة الفعالية ↗</a>
        : <p>تواصل مع مسؤول الفعالية لمراجعة حصة الدعوات.</p>)}
      {waiting && <>
        <p>{seconds > 0 ? `يمكنك إعادة المحاولة بعد ${seconds.toLocaleString('ar')} ثانية.` : 'يمكنك إعادة المحاولة الآن.'}</p>
        {onRetry && <button type="button" disabled={seconds > 0 || busy} onClick={onRetry}>إعادة المحاولة</button>}
      </>}
    </div>
    {showPlans && createPortal(<PricingModal isOpen currentPlanCode={currentPlanCode} onClose={() => setShowPlans(false)} />, document.body)}
  </>
}
