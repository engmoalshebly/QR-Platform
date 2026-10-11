import { getApiErrorMessage } from '@services/http/client'
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  X,
  Check,
  Loader2,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  AlertCircle,
  SlidersHorizontal,
  Clock,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  subscriptionsAPI,
  type Plan,
} from '../../settings/api/subscriptionsApi'
import { useAuthStore } from '@features/auth/store/authStore'
import { formatUsd, formatYer } from '@shared/utils/currency'
import { CustomPlanBuilder } from './CustomPlanBuilder'
import './pricing.css'

interface PricingModalProps {
  isOpen: boolean
  onClose: () => void
  currentPlanCode?: string
  /** True inside the renewal window of a running paid plan (API: renewal_open). */
  renewalOpen?: boolean
}

const LIMIT_LABELS: Record<string, string> = {
  events_per_month: 'الفعاليات شهرياً',
  invitations_per_event: 'الدعوات لكل حدث',
  seats_max: 'المستخدمين في المنصة',
  storage_mb: 'مساحة التخزين',
}

function formatLimitValue(key: string, value: number) {
  if (value === -1) return 'غير محدود'
  if (key === 'storage_mb') {
    if (value >= 1000) return `${value / 1000} جيجابايت`
    return `${value} ميجابايت`
  }
  return value.toLocaleString('ar')
}

export function PricingModal({ isOpen, onClose, currentPlanCode = 'starter', renewalOpen = false }: PricingModalProps) {
  const queryClient = useQueryClient()
  const currentTenantId = useAuthStore((s) => s.currentTenantId)

  // Step flow: 'plans' -> 'custom' -> 'checkout' -> 'success'
  const [step, setStep] = useState<'plans' | 'custom' | 'checkout' | 'success'>('plans')
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'yearly'>('monthly')
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)
  const [customPlanCtx, setCustomPlanCtx] = useState<{ id: string; name: string; totalMonthly: number; totalYearly: number } | null>(null)
  const [paymentNotes, setPaymentNotes] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Reset state on modal open/close
  useEffect(() => {
    if (!isOpen) {
      setStep('plans')
      setSelectedPlan(null)
      setCustomPlanCtx(null)
      setPaymentNotes('')
      setErrorMessage(null)
    }
  }, [isOpen])

  // Fetch plans
  const { data: plans, isLoading: isPlansLoading, error: plansError } = useQuery({
    queryKey: ['pricing-plans'],
    queryFn: subscriptionsAPI.listPlans,
    enabled: isOpen,
  })

  // Submit a plan request for staff review. Nothing activates immediately —
  // see /platform/subscription-requests and /platform/custom-plans/pending.
  const requestMutation = useMutation({
    mutationFn: async () => {
      if (customPlanCtx) {
        return subscriptionsAPI.requestCustomPlanActivation(customPlanCtx.id, billingPeriod, paymentNotes.trim() || undefined)
      }
      if (!selectedPlan) throw new Error('يرجى اختيار باقة')
      return subscriptionsAPI.requestSubscription(selectedPlan.code, billingPeriod, paymentNotes.trim() || undefined)
    },
    onSuccess: () => {
      setErrorMessage(null)
      setStep('success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['current-subscription'] })
    },
    onError: (err: any) => {
      const msg = getApiErrorMessage(err, 'تعذر إرسال الطلب. يرجى المحاولة مرة أخرى.')
      setErrorMessage(msg)
    },
  })

  if (!isOpen) return null

  const sortedPlans = plans ? [...plans].sort((a, b) => a.sort_order - b.sort_order) : []
  const currentPlan = sortedPlans.find(p => p.code.toLowerCase() === currentPlanCode.toLowerCase())
  const currentSortOrder = currentPlan?.sort_order || 1

  return (
    <AnimatePresence>
      <motion.div
        className="pricing-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className={`pricing-modal ${step !== 'plans' ? 'pricing-modal--checkout' : ''}`}
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ type: 'spring', stiffness: 350, damping: 28 }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Close button */}
          <button className="pricing-modal__close" onClick={onClose} aria-label="إغلاق">
            <X size={20} />
          </button>

          {/* ══════════════════════════════════════════════
              VIEW 1: PLANS COMPARISON
             ══════════════════════════════════════════════ */}
          {step === 'plans' && (
            <>
              {/* Header */}
              <div className="pricing-modal__header">
                <span className="dash-pill" style={{ color: '#c9a96e', background: 'rgba(201,169,110,0.08)' }}>
                  <Sparkles size={14} className="spin" /> خطط الاشتراك وترقية الباقات
                </span>
                <h2 className="pricing-modal__title">اختر الخطة المناسبة لفعالياتك</h2>
                <p className="pricing-modal__subtitle">
                  ادفع بسهولة عبر محفظتك الإلكترونية المحلية (فلوسك، جيب، إيزي) مع تفعيل فوري للاشتراك.
                </p>

                {/* Toggle Billing Period */}
                <div className="pricing-toggle-container">
                  <button
                    type="button"
                    className={`pricing-toggle-btn ${billingPeriod === 'monthly' ? 'pricing-toggle-btn--active' : ''}`}
                    onClick={() => setBillingPeriod('monthly')}
                  >
                    شهرياً
                  </button>
                  <button
                    type="button"
                    className={`pricing-toggle-btn ${billingPeriod === 'yearly' ? 'pricing-toggle-btn--active' : ''}`}
                    onClick={() => setBillingPeriod('yearly')}
                  >
                    سنوياً
                    <span className="pricing-toggle-discount">خصم شهريين</span>
                  </button>
                </div>

                {/* Custom Plan Builder Entry */}
                <button
                  type="button"
                  className="custom-plan-entry-btn"
                  onClick={() => {
                    setSelectedPlan(null)
                    setCustomPlanCtx(null)
                    setErrorMessage(null)
                    setStep('custom')
                  }}
                >
                  <SlidersHorizontal size={16} />
                  صمّم باقتك المخصصة — ادفع فقط مقابل ما تحتاجه
                </button>
              </div>

              {/* Content */}
              <div className="pricing-modal__content">
                {isPlansLoading ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '300px', gap: '16px' }}>
                    <Loader2 size={40} className="spin" style={{ color: '#c9a96e' }} />
                    <span style={{ color: '#94a3b8', fontSize: '14px' }}>جاري تحميل خطط الاشتراك والأسعار…</span>
                  </div>
                ) : plansError ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '300px', gap: '12px', textAlign: 'center' }}>
                    <span style={{ color: '#f87171', fontSize: '15px', fontWeight: 600 }}>فشل تحميل خطط الاشتراك</span>
                    <span style={{ color: '#64748b', fontSize: '13px' }}>يرجى التحقق من الاتصال وإعادة المحاولة.</span>
                  </div>
                ) : (
                  <div className="pricing-grid">
                    {sortedPlans.map((plan) => {
                      const isCurrent = plan.code.toLowerCase() === currentPlanCode.toLowerCase()
                      const isEnterprise = plan.code.toLowerCase() === 'enterprise'
                      const isPopular = plan.is_popular

                      const price = billingPeriod === 'monthly' ? plan.price_monthly : Math.round(plan.price_yearly / 12)

                      let btnLabel = 'ترقية الباقة'
                      let isDisabled = false
                      let btnVariant: 'primary' | 'secondary' = 'secondary'

                      if (isCurrent && renewalOpen) {
                        // Same plan, close to its end: renewing is allowed (the API keeps the days left).
                        btnLabel = 'تجديد الاشتراك'
                        btnVariant = 'primary'
                      } else if (isCurrent) {
                        btnLabel = 'الباقة الحالية'
                        isDisabled = true
                        btnVariant = 'secondary'
                      } else if (isEnterprise) {
                        btnLabel = 'تواصل معنا'
                        btnVariant = 'secondary'
                      } else if (plan.sort_order < currentSortOrder) {
                        btnLabel = 'تغيير الباقة'
                        btnVariant = 'secondary'
                      } else {
                        btnLabel = 'ترقية الآن'
                        btnVariant = 'primary'
                      }

                      const eventLimit = plan.limits.find(l => l.key === 'events_per_month')?.value ?? 0
                      const invitationLimit = plan.limits.find(l => l.key === 'invitations_per_event')?.value ?? 0
                      const seatsLimit = plan.limits.find(l => l.key === 'seats_max')?.value ?? 0
                      const storageLimit = plan.limits.find(l => l.key === 'storage_mb')?.value ?? 0

                      return (
                        <div
                          key={plan.id}
                          className={`plan-card ${isPopular ? 'plan-card--popular' : ''}`}
                        >
                          {isPopular && <div className="plan-popular-badge">الأكثر شعبية</div>}

                          <div className="plan-card__header">
                            <h3 className="plan-card__name">{plan.name}</h3>
                            <p className="plan-card__desc">{plan.description}</p>
                          </div>

                          <div className="plan-card__pricing">
                            {isEnterprise ? (
                              <span className="plan-card__price-label">تسعير خاص</span>
                            ) : (
                              <>
                                <span className="plan-card__price-amount">
                                  ${formatUsd(price)}
                                </span>
                                <span className="plan-card__price-period">/ شهر</span>
                                {price > 0 && (
                                  <span className="plan-card__price-yer">≈ {formatYer(price)} ر.ي</span>
                                )}
                              </>
                            )}
                          </div>

                          <div className="plan-limits-summary">
                            <div className="limit-item">
                              <span>{LIMIT_LABELS.events_per_month}</span>
                              <strong className={eventLimit === -1 ? 'ar' : ''}>
                                {formatLimitValue('events_per_month', eventLimit)}
                              </strong>
                            </div>
                            <div className="limit-item">
                              <span>{LIMIT_LABELS.invitations_per_event}</span>
                              <strong className={invitationLimit === -1 ? 'ar' : ''}>
                                {formatLimitValue('invitations_per_event', invitationLimit)}
                              </strong>
                            </div>
                            <div className="limit-item">
                              <span>{LIMIT_LABELS.seats_max}</span>
                              <strong className={seatsLimit === -1 ? 'ar' : ''}>
                                {formatLimitValue('seats_max', seatsLimit)}
                              </strong>
                            </div>
                            <div className="limit-item">
                              <span>{LIMIT_LABELS.storage_mb}</span>
                              <strong className={storageLimit === -1 ? 'ar' : ''}>
                                {formatLimitValue('storage_mb', storageLimit)}
                              </strong>
                            </div>
                          </div>

                          <div className="plan-features-list">
                            {(plan.features || []).slice(0, 7).map((feat, idx) => (
                              <div key={idx} className="feature-check-item">
                                <Check size={14} />
                                <span>{feat}</span>
                              </div>
                            ))}
                          </div>

                          <button
                            type="button"
                            className={`plan-card__btn plan-card__btn--${btnVariant}`}
                            disabled={isDisabled}
                            onClick={() => {
                              if (isEnterprise) {
                                window.location.href = 'mailto:sales@qentry.com?subject=طلب ترقية لباقة Enterprise'
                              } else {
                                setCustomPlanCtx(null)
                                setSelectedPlan(plan)
                                setErrorMessage(null)
                                setStep('checkout')
                              }
                            }}
                          >
                            {isCurrent ? null : <Sparkles size={14} />}
                            {btnLabel}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </>
          )}

          {/* ══════════════════════════════════════════════
              VIEW 1.5: CUSTOM PLAN BUILDER
             ══════════════════════════════════════════════ */}
          {step === 'custom' && (
            <CustomPlanBuilder
              plans={sortedPlans}
              onBack={() => {
                setStep('plans')
                setErrorMessage(null)
              }}
              onReadyToPay={(ctx) => {
                setCustomPlanCtx(ctx)
                setSelectedPlan(null)
                setErrorMessage(null)
                setStep('checkout')
              }}
            />
          )}

          {/* ══════════════════════════════════════════════
              VIEW 2: SUBMIT FOR STAFF REVIEW
             ══════════════════════════════════════════════ */}
          {step === 'checkout' && (selectedPlan || customPlanCtx) && (
            <div className="link-checkout">
              <button
                type="button"
                className="link-checkout__back-btn"
                onClick={() => {
                  setStep(customPlanCtx ? 'custom' : 'plans')
                  setErrorMessage(null)
                }}
              >
                <ArrowRight size={16} /> {customPlanCtx ? 'العودة لمصمم الباقة' : 'العودة للباقات'}
              </button>

              <div className="link-checkout__header">
                <div className="link-checkout__icon">
                  <ShieldCheck size={28} />
                </div>
                <h2>إرسال طلب تفعيل الباقة</h2>
                <p>يراجع فريقنا الطلب بعد التحقق من الدفع (حوالة بنكية أو نقداً) ثم يفعّل الباقة لحسابك.</p>
              </div>

              {errorMessage && (
                <div className="link-checkout__alert link-checkout__alert--error">
                  <AlertCircle size={18} />
                  <span>{errorMessage}</span>
                </div>
              )}

              {/* Selected Plan Summary Card */}
              <div className="link-checkout__summary">
                <div className="link-checkout__summary-row">
                  <div>
                    <strong>{customPlanCtx ? customPlanCtx.name : `باقة ${selectedPlan?.name}`}</strong>
                    <span style={{ display: 'block', fontSize: '12px', color: 'var(--color-text-muted)', marginTop: '2px' }}>
                      {billingPeriod === 'monthly' ? 'اشتراك لمدة شهر (30 يوماً)' : 'اشتراك سنوي (12 شهراً)'}
                    </span>
                  </div>
                  <div className="link-checkout__summary-price">
                    <strong>
                      ${formatUsd((customPlanCtx
                        ? (billingPeriod === 'monthly' ? customPlanCtx.totalMonthly : customPlanCtx.totalYearly)
                        : (billingPeriod === 'monthly' ? selectedPlan?.price_monthly : selectedPlan?.price_yearly)
                      ) ?? 0)}
                    </strong>
                    <span style={{ display: 'block', fontSize: '12px', color: 'var(--color-text-muted)' }}>
                      ≈ {formatYer((customPlanCtx
                        ? (billingPeriod === 'monthly' ? customPlanCtx.totalMonthly : customPlanCtx.totalYearly)
                        : (billingPeriod === 'monthly' ? selectedPlan?.price_monthly : selectedPlan?.price_yearly)
                      ) ?? 0)} ر.ي
                    </span>
                  </div>
                </div>
              </div>

              {/* Payment notes */}
              <div className="link-checkout__field-group">
                <label className="link-checkout__label" htmlFor="payment-notes-input">
                  كيف ستتم عملية الدفع؟ (اختياري)
                </label>
                <textarea
                  id="payment-notes-input"
                  className="link-checkout__input"
                  style={{ minHeight: '84px', resize: 'vertical' }}
                  placeholder="مثال: حوالة بنكية رقم ١٢٣٤٥ عبر بنك القاسمي، أو سيتم الدفع نقداً عند الزيارة"
                  value={paymentNotes}
                  onChange={(e) => setPaymentNotes(e.target.value)}
                />
                <span className="link-checkout__hint">
                  هذه الملاحظة تساعد فريقنا على التحقق من الدفع بسرعة. الدفع عبر المحفظة الإلكترونية غير متاح حالياً.
                </span>
              </div>

              {/* Action Button */}
              <button
                type="button"
                className="link-checkout__submit-btn"
                disabled={requestMutation.isPending}
                onClick={() => requestMutation.mutate()}
              >
                {requestMutation.isPending ? (
                  <>
                    <Loader2 size={18} className="spin" />
                    جاري إرسال الطلب…
                  </>
                ) : (
                  <>
                    <ShieldCheck size={18} />
                    إرسال الطلب للمراجعة
                  </>
                )}
              </button>
            </div>
          )}

          {/* ══════════════════════════════════════════════
              VIEW 3: REQUEST SUBMITTED
             ══════════════════════════════════════════════ */}
          {step === 'success' && (
            <div className="link-checkout link-checkout--success">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', damping: 15, stiffness: 200 }}
                className="link-checkout__success-icon"
              >
                <Clock size={56} />
              </motion.div>
              <h2>تم استلام طلبك</h2>
              <p>
                طلبك لتفعيل <strong>{customPlanCtx?.name || selectedPlan?.name || 'الباقة الجديدة'}</strong> قيد مراجعة فريقنا.
                سيتم تفعيلها وإشعارك بعد التحقق من الدفع.
              </p>
              <div className="link-checkout__success-badge">
                <Clock size={16} /> قيد المراجعة
              </div>
              <button type="button" className="link-checkout__submit-btn" style={{ marginTop: '18px' }} onClick={onClose}>
                حسناً
              </button>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
