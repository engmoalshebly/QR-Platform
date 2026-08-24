import { useState } from 'react'
import { motion } from 'framer-motion'
import { Crown, CalendarClock, Sparkles } from 'lucide-react'
import type { DashboardSubscription } from '../types'
import { PricingModal } from './PricingModal'

const statusLabel: Record<string, string> = {
  active: 'نشط',
  trial: 'تجريبي',
  trialing: 'تجريبي',
  cancelled: 'ملغي',
  past_due: 'متأخر',
}

function daysRemaining(endDate?: string | null): number | null {
  if (!endDate) return null
  const end = new Date(endDate).getTime()
  if (isNaN(end)) return null
  return Math.max(0, Math.ceil((end - Date.now()) / 86400000))
}

function formatDate(value?: string | null): string {
  if (!value) return 'غير متوفر'
  const date = new Date(value)
  if (isNaN(date.getTime())) return 'غير متوفر'
  return new Intl.DateTimeFormat('ar', { dateStyle: 'medium' }).format(date)
}

interface SubscriptionCardProps {
  subscription: DashboardSubscription | null
  planFallback?: string
}

export function SubscriptionCard({ subscription, planFallback }: SubscriptionCardProps) {
  const [isPricingOpen, setIsPricingOpen] = useState(false)
  const plan = subscription?.plan_name || planFallback || 'Free'
  const price = subscription?.price_monthly ?? 0
  const status = subscription?.sub_status || 'active'
  const days = daysRemaining(subscription?.current_period_end)
  
  const planCode = subscription?.plan_code || planFallback || 'starter'
  const isEnterprise = planCode.toLowerCase() === 'enterprise'

  return (
    <>
      <motion.div
        className="subscription-card"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.2 }}
      >
        {/* header */}
        <div className={`subscription-card__header ${price > 0 ? 'subscription-card__header--premium' : ''}`}>
          <div className="subscription-card__plan-row">
            <Crown size={18} />
            <span className="subscription-card__plan-name">{plan}</span>
          </div>
          <span className={`subscription-card__badge subscription-card__badge--${status}`}>
            {statusLabel[status] || status}
          </span>
        </div>

        {/* price */}
        <div className="subscription-card__price">
          <strong>{price > 0 ? price.toLocaleString('en-US') : '0'}</strong>
          <span>ر.ي / شهريًا</span>
        </div>

        {/* details */}
        <div className="subscription-card__details">
          <div className="subscription-card__row">
            <CalendarClock size={14} />
            <span>نهاية الفترة</span>
            <strong>{formatDate(subscription?.current_period_end)}</strong>
          </div>
          {days !== null && (
            <div className="subscription-card__row">
              <Sparkles size={14} />
              <span>الأيام المتبقية</span>
              <strong className={days <= 7 ? 'text-warning' : ''}>{days} يوم</strong>
            </div>
          )}
        </div>

        {/* upgrade CTA (visible for plans below enterprise) */}
        {!isEnterprise && (
          <button
            className="subscription-card__cta"
            type="button"
            onClick={() => setIsPricingOpen(true)}
          >
            <Sparkles size={14} />
            ترقية الآن
          </button>
        )}
      </motion.div>

      <PricingModal
        isOpen={isPricingOpen}
        onClose={() => setIsPricingOpen(false)}
        currentPlanCode={planCode}
      />
    </>
  )
}
