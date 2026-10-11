import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Lock } from 'lucide-react'
import { subscriptionsAPI } from '@features/settings/api/subscriptionsApi'
import { PricingModal } from '@features/dashboard/components/PricingModal'
import { useAuthStore } from '@features/auth/store/authStore'
import { usePermission, PERM } from '@shared/permissions'
import './subscription-status-banner.css'

const fmt = (iso?: string | null) =>
  iso ? new Intl.DateTimeFormat('ar', { dateStyle: 'medium' }).format(new Date(iso)) : ''

/**
 * Shown on every workspace page when the paid plan has ended (read-only mode) or
 * is about to end.  Platform staff have no workspace and never see it.
 */
export function SubscriptionStatusBanner() {
  const tenantId = useAuthStore(s => s.currentTenantId)
  const isStaff = useAuthStore(s => Boolean(s.user?.is_staff))
  const canManageBilling = usePermission(PERM.BILLING_MANAGE)
  const [open, setOpen] = useState(false)

  const { data } = useQuery({
    queryKey: ['subscription-status', tenantId],
    queryFn: subscriptionsAPI.getStatus,
    enabled: Boolean(tenantId) && !isStaff,
    staleTime: 60_000,
    retry: false,
  })
  if (!data) return null

  const expired = data.expired
  const ending = !expired && data.renewal_open && data.days_left !== null && data.days_left <= 7
  if (!expired && !ending) return null

  const action = data.request_pending
    ? <span className="sub-banner__note">طلب التجديد قيد مراجعة فريق المنصة.</span>
    : canManageBilling
      ? <button type="button" className="sub-banner__btn" onClick={() => setOpen(true)}>تجديد الاشتراك</button>
      : <span className="sub-banner__note">تواصل مع مالك الحساب لتجديد الاشتراك.</span>

  return (
    <>
      <div className={`sub-banner sub-banner--${expired ? 'expired' : 'ending'}`} role="status">
        {expired ? <Lock size={18} /> : <AlertTriangle size={18} />}
        <p>
          {expired
            ? <>انتهى اشتراكك{data.plan_name ? ` في باقة ${data.plan_name}` : ''}{data.ended_at ? ` بتاريخ ${fmt(data.ended_at)}` : ''}.
                المساحة الآن في <strong>وضع العرض فقط</strong>؛ بياناتك محفوظة وكل شيء يعود للعمل فور تفعيل التجديد.</>
            : <>ينتهي اشتراكك خلال {data.days_left} يوم ({fmt(data.period_end)}). جدّد الآن، والأيام المتبقية تُضاف إلى المدة الجديدة.</>}
        </p>
        {action}
      </div>
      {open && <PricingModal isOpen onClose={() => setOpen(false)} currentPlanCode={expired ? 'starter' : (data.plan_code ?? 'starter')} renewalOpen={!expired} />}
    </>
  )
}
