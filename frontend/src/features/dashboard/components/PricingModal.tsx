import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  X,
  Check,
  Loader2,
  Sparkles,
  ArrowRight,
  Wallet,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  QrCode,
  Smartphone,
  SlidersHorizontal,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  subscriptionsAPI,
  type Plan,
  type PaymentProvider,
  type InitiatePaymentResponse,
} from '../../settings/api/subscriptionsApi'
import { useAuthStore } from '@features/auth/store/authStore'
import { CustomPlanBuilder } from './CustomPlanBuilder'
import './pricing.css'

interface PricingModalProps {
  isOpen: boolean
  onClose: () => void
  currentPlanCode?: string
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

// Fallback wallet providers if backend service is unreachable
const DEFAULT_PROVIDERS: PaymentProvider[] = [
  { code: 'Easy', name: 'محفظة إيزي', nameEn: 'Easy Wallet', available: true },
  { code: 'Cash', name: 'محفظة كاش', nameEn: 'Cash Wallet', available: true },
  { code: 'Floosak', name: 'محفظة فلوسك', nameEn: 'Floosak', available: true },
  { code: 'kuraimi', name: 'كريمي جوال', nameEn: 'Kuraimi Jawwal', available: true },
  { code: 'Jaib', name: 'محفظة جيب', nameEn: 'Jaib Wallet', available: true },
]

const WALLET_BRANDS: Record<string, { bg: string; color: string; accent: string }> = {
  Cash: { bg: 'linear-gradient(135deg, rgba(14, 165, 233, 0.12), rgba(2, 132, 199, 0.04))', color: '#0284c7', accent: '#0ea5e9' },
  Easy: { bg: 'linear-gradient(135deg, rgba(249, 115, 22, 0.12), rgba(234, 88, 12, 0.04))', color: '#ea580c', accent: '#f97316' },
  EasyBeta: { bg: 'linear-gradient(135deg, rgba(249, 115, 22, 0.12), rgba(234, 88, 12, 0.04))', color: '#ea580c', accent: '#f97316' },
  Floosak: { bg: 'linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(5, 150, 105, 0.04))', color: '#059669', accent: '#10b981' },
  Jaib: { bg: 'linear-gradient(135deg, rgba(139, 92, 246, 0.12), rgba(124, 58, 237, 0.04))', color: '#7c3aed', accent: '#8b5cf6' },
  kuraimi: { bg: 'linear-gradient(135deg, rgba(37, 99, 235, 0.12), rgba(29, 78, 216, 0.04))', color: '#1d4ed8', accent: '#2563eb' },
  Jawali: { bg: 'linear-gradient(135deg, rgba(236, 72, 153, 0.12), rgba(219, 39, 119, 0.04))', color: '#db2777', accent: '#ec4899' },
  ONECASH: { bg: 'linear-gradient(135deg, rgba(225, 29, 72, 0.12), rgba(190, 18, 60, 0.04))', color: '#be123c', accent: '#e11d48' },
  SabaCash: { bg: 'linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(217, 119, 6, 0.04))', color: '#d97706', accent: '#f59e0b' },
}

export function PricingModal({ isOpen, onClose, currentPlanCode = 'starter' }: PricingModalProps) {
  const queryClient = useQueryClient()
  const currentTenantId = useAuthStore((s) => s.currentTenantId)

  // Step flow: 'plans' -> 'custom' -> 'checkout' -> 'otp' -> 'success'
  const [step, setStep] = useState<'plans' | 'custom' | 'checkout' | 'otp' | 'success'>('plans')
  const [billingPeriod, setBillingPeriod] = useState<'monthly' | 'yearly'>('monthly')
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)
  const [customPlanCtx, setCustomPlanCtx] = useState<{ id: string; name: string; totalMonthly: number; totalYearly: number } | null>(null)
  const [selectedProvider, setSelectedProvider] = useState<string>('Easy')
  const [walletNumber, setWalletNumber] = useState<string>('')
  const [otpCode, setOtpCode] = useState<string>('')
  const [paymentInitiation, setPaymentInitiation] = useState<InitiatePaymentResponse | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [showRecover, setShowRecover] = useState<boolean>(false)
  const [showQr, setShowQr] = useState<boolean>(false)

  // Reset state on modal open/close
  useEffect(() => {
    if (!isOpen) {
      setStep('plans')
      setSelectedPlan(null)
      setCustomPlanCtx(null)
      setWalletNumber('')
      setOtpCode('')
      setPaymentInitiation(null)
      setErrorMessage(null)
      setShowRecover(false)
      setShowQr(false)
    }
  }, [isOpen])

  // Fetch plans
  const { data: plans, isLoading: isPlansLoading, error: plansError } = useQuery({
    queryKey: ['pricing-plans'],
    queryFn: subscriptionsAPI.listPlans,
    enabled: isOpen,
  })

  // Fetch wallet providers
  const { data: providersData } = useQuery({
    queryKey: ['payment-providers'],
    queryFn: subscriptionsAPI.getPaymentProviders,
    enabled: isOpen,
  })

  const providers: PaymentProvider[] = providersData?.providers?.length
    ? providersData.providers
    : DEFAULT_PROVIDERS

  // Step 1: Initiate Payment Mutation
  const initiateMutation = useMutation({
    mutationFn: async () => {
      if (!walletNumber.trim()) throw new Error('يرجى إدخال رقم المحفظة')
      if (customPlanCtx) {
        return subscriptionsAPI.initiateCustomPlanPayment(
          customPlanCtx.id,
          selectedProvider,
          walletNumber.trim(),
          billingPeriod,
        )
      }
      if (!selectedPlan) throw new Error('يرجى اختيار باقة')
      return subscriptionsAPI.initiatePayment(
        selectedPlan.code,
        selectedProvider,
        walletNumber.trim(),
        billingPeriod,
      )
    },
    onSuccess: (data) => {
      setErrorMessage(null)
      setShowRecover(false)
      setPaymentInitiation(data)
      // Check if it was a dev mock bypass
      if (data.status === 'MOCK_SUCCESS') {
        setStep('success')
        queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
        queryClient.invalidateQueries({ queryKey: ['current-subscription'] })
        setTimeout(() => {
          onClose()
        }, 2200)
      } else {
        setStep('otp')
      }
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || err.message || 'فشلت عملية بدء الدفع. يرجى التحقق من صحة البيانات.'
      setErrorMessage(msg)
    },
  })

  // Step 2: Confirm OTP Mutation
  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!paymentInitiation?.payment_id) throw new Error('معرف الدفع غير متوفر')
      if (!otpCode.trim()) throw new Error('يرجى إدخال رمز التحقق OTP')
      return subscriptionsAPI.confirmPaymentOTP(
        paymentInitiation.payment_id,
        otpCode.trim(),
      )
    },
    onSuccess: () => {
      setErrorMessage(null)
      setStep('success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['current-subscription'] })
      setTimeout(() => {
        onClose()
      }, 2500)
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || err.message || 'رمز التحقق غير صحيح أو منتهي الصلاحية.'
      setErrorMessage(msg)
      // If the wallet was already charged but activation failed, the user
      // can complete activation without paying again.
      setShowRecover(true)
    },
  })

  // Recovery: complete activation for an already-paid payment (no new charge)
  const recoverMutation = useMutation({
    mutationFn: async () => {
      if (!paymentInitiation?.payment_id) throw new Error('معرف الدفع غير متوفر')
      return subscriptionsAPI.recoverPayment(paymentInitiation.payment_id)
    },
    onSuccess: () => {
      setErrorMessage(null)
      setShowRecover(false)
      setStep('success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['current-subscription'] })
      setTimeout(() => {
        onClose()
      }, 2500)
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || err.message || 'تعذر استكمال التفعيل. تأكد من إتمام الدفع أولاً.'
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

                      if (isCurrent) {
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
                                  {price === 0 ? '0' : price.toLocaleString('en-US')}
                                </span>
                                <span className="plan-card__price-period">ر.ي / شهر</span>
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
              VIEW 2: LINK GATEWAY WALLET CHECKOUT
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
                  <Wallet size={28} />
                </div>
                <h2>الدفع عبر المحفظة الإلكترونية</h2>
                <p>اختر محفظتك وأدخل رقم الحساب لإرسال رمز التأكيد (OTP)</p>
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
                      {(customPlanCtx
                        ? (billingPeriod === 'monthly' ? customPlanCtx.totalMonthly : customPlanCtx.totalYearly)
                        : (billingPeriod === 'monthly' ? selectedPlan?.price_monthly : selectedPlan?.price_yearly)
                      )?.toLocaleString('en-US')}
                    </strong>
                    <span>ر.ي</span>
                  </div>
                </div>
              </div>

              {/* Wallet Providers Selection */}
              <div className="link-checkout__field-group">
                <div className="link-checkout__field-header">
                  <label className="link-checkout__label">اختر المحفظة الإلكترونية:</label>
                  <span className="link-checkout__counter">{providers.length} محفظة متاحة</span>
                </div>
                <div className="link-checkout__wallets-grid">
                  {providers.map((p) => {
                    const isSelected = selectedProvider === p.code
                    const brand = WALLET_BRANDS[p.code] || {
                      bg: 'linear-gradient(135deg, rgba(99, 102, 241, 0.12), rgba(79, 70, 229, 0.04))',
                      color: '#6366f1',
                      accent: '#818cf8',
                    }
                    const logoSrc = p.logoUrl || (p.logo && p.logo.startsWith('http') ? p.logo : undefined)

                    return (
                      <button
                        key={p.code}
                        type="button"
                        className={`link-wallet-card ${isSelected ? 'link-wallet-card--selected' : ''}`}
                        onClick={() => setSelectedProvider(p.code)}
                        style={{
                          '--brand-color': brand.color,
                          '--brand-accent': brand.accent,
                          '--brand-bg': brand.bg,
                        } as React.CSSProperties}
                      >
                        <div className="link-wallet-card__header">
                          <div className="link-wallet-card__avatar">
                            {logoSrc ? (
                              <img
                                src={logoSrc}
                                alt={p.name}
                                className="link-wallet-card__logo"
                                onError={(e) => {
                                  (e.target as HTMLElement).style.display = 'none';
                                  const fallback = (e.target as HTMLElement).nextElementSibling as HTMLElement;
                                  if (fallback) fallback.style.display = 'flex';
                                }}
                              />
                            ) : null}
                            <div
                              className="link-wallet-card__fallback"
                              style={{ display: logoSrc ? 'none' : 'flex' }}
                            >
                              <Wallet size={16} />
                            </div>
                          </div>

                          <div className="link-wallet-card__radio">
                            {isSelected && <Check size={12} strokeWidth={3} className="link-wallet-card__check" />}
                          </div>
                        </div>

                        <div className="link-wallet-card__body">
                          <span className="link-wallet-card__name">{p.name}</span>
                          {p.nameEn && <span className="link-wallet-card__name-en">{p.nameEn}</span>}
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Wallet Number Input */}
              <div className="link-checkout__field-group">
                <label className="link-checkout__label" htmlFor="wallet-number-input">
                  رقم المحفظة / الهاتف:
                </label>
                <input
                  id="wallet-number-input"
                  type="text"
                  dir="ltr"
                  className="link-checkout__input"
                  placeholder="77XXXXXXX أو 73XXXXXXX"
                  value={walletNumber}
                  onChange={(e) => setWalletNumber(e.target.value)}
                  autoFocus
                />
                <span className="link-checkout__hint">
                  سيصلك رمز تحقق (OTP) عبر رسالة SMS أو إشعار في تطبيق المحفظة.
                </span>
              </div>

              {/* Action Button */}
              <button
                type="button"
                className="link-checkout__submit-btn"
                disabled={initiateMutation.isPending || !walletNumber.trim()}
                onClick={() => initiateMutation.mutate()}
              >
                {initiateMutation.isPending ? (
                  <>
                    <Loader2 size={18} className="spin" />
                    جاري إرسال رمز التحقق…
                  </>
                ) : (
                  <>
                    <ShieldCheck size={18} />
                    إرسال رمز التحقق (OTP)
                  </>
                )}
              </button>
            </div>
          )}

          {/* ══════════════════════════════════════════════
              VIEW 3: OTP & QR CODE CONFIRMATION
             ══════════════════════════════════════════════ */}
          {step === 'otp' && (
            <div className="link-checkout">
              <button
                type="button"
                className="link-checkout__back-btn"
                onClick={() => {
                  setStep('checkout')
                  setErrorMessage(null)
                  setShowQr(false)
                }}
              >
                <ArrowRight size={16} /> تعديل بيانات المحفظة
              </button>

              <div className="link-checkout__header">
                <div className="link-checkout__icon link-checkout__icon--otp">
                  <ShieldCheck size={28} />
                </div>
                <h2>تأكيد عملية الدفع</h2>
                <p>
                  تم إنشاء طلب الدفع بنجاح عبر بوابة <strong>Link Gateway</strong>
                </p>
              </div>

              {/* Selected Wallet Banner */}
              {(() => {
                const activeP = providers.find((p) => p.code === selectedProvider) || { name: selectedProvider, code: selectedProvider }
                const logoSrc = activeP.logoUrl || (activeP.logo && activeP.logo.startsWith('http') ? activeP.logo : undefined)
                const brand = WALLET_BRANDS[activeP.code] || { color: '#6366f1' }

                return (
                  <div className="link-checkout__active-wallet-card">
                    <div className="link-checkout__active-wallet-avatar">
                      {logoSrc ? (
                        <img src={logoSrc} alt={activeP.name} />
                      ) : (
                        <Smartphone size={20} style={{ color: brand.color }} />
                      )}
                    </div>
                    <div className="link-checkout__active-wallet-info">
                      <strong>{activeP.name}</strong>
                      <span>رقم الحساب: {walletNumber}</span>
                    </div>
                    <div className="link-checkout__active-wallet-badge">
                      <ShieldCheck size={13} /> جلسة دفع نشطة
                    </div>
                  </div>
                )
              })()}

              {errorMessage && (
                <div className="link-checkout__alert link-checkout__alert--error">
                  <AlertCircle size={18} />
                  <span>{errorMessage}</span>
                </div>
              )}

              {paymentInitiation && (
                <div className="link-checkout__details-card">
                  <div className="link-checkout__details-row">
                    <span>المبلغ المطلوب:</span>
                    <strong>{paymentInitiation.total_amount?.toLocaleString('en-US') || selectedPlan?.price_monthly.toLocaleString('en-US')} ر.ي</strong>
                  </div>
                  {paymentInitiation.fees > 0 && (
                    <div className="link-checkout__details-row">
                      <span>رسوم البوابة:</span>
                      <span>{paymentInitiation.fees} ر.ي</span>
                    </div>
                  )}
                </div>
              )}

              {/* Toggle QR Code Option */}
              <div className="link-checkout__qr-toggle-container">
                <button
                  type="button"
                  className={`link-checkout__qr-toggle-btn ${showQr ? 'link-checkout__qr-toggle-btn--active' : ''}`}
                  onClick={() => setShowQr(!showQr)}
                >
                  <QrCode size={16} />
                  <span>{showQr ? 'إخفاء الباركود والعودة لرمز OTP' : 'أو ادفع بمسح الباركود (QR Code)'}</span>
                </button>

                {showQr && (
                  <motion.div
                    className="link-checkout__qr-box"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                  >
                    <div className="link-checkout__qr-frame">
                      <img
                        src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(`https://payment-test.tharwatt.com:5243/checkout/link/bill/11770/${paymentInitiation?.payment_id || 'DEMO'}`)}`}
                        alt="Payment QR Code"
                        className="link-checkout__qr-img"
                      />
                    </div>
                    <p className="link-checkout__qr-caption">
                      امسح الباركود بكاميرا الهاتف أو تطبيق المحفظة للدفع الفوري
                    </p>
                  </motion.div>
                )}
              </div>

              {/* OTP Code Input */}
              <div className="link-checkout__field-group">
                <label className="link-checkout__label" htmlFor="otp-input">
                  أدخل رمز التحقق (OTP):
                </label>
                <input
                  id="otp-input"
                  type="text"
                  dir="ltr"
                  maxLength={10}
                  className="link-checkout__input link-checkout__input--otp"
                  placeholder="• • • • • •"
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.target.value)}
                  autoFocus
                />
                <p style={{ fontSize: '0.78rem', color: '#10b981', marginTop: '6px', textAlign: 'center' }}>
                  💡 بيئة الاختبار التجريبية: أدخل <strong>123456</strong> أو أي 6 أرقام لتأكيد الدفع وتفعيل الباقة فوراً.
                </p>
              </div>

              {/* Confirm Button */}
              <button
                type="button"
                className="link-checkout__submit-btn link-checkout__submit-btn--confirm"
                disabled={confirmMutation.isPending || !otpCode.trim()}
                onClick={() => confirmMutation.mutate()}
              >
                {confirmMutation.isPending ? (
                  <>
                    <Loader2 size={18} className="spin" />
                    جاري تأكيد الدفع وتفعيل الباقة…
                  </>
                ) : (
                  <>
                    <CheckCircle2 size={18} />
                    تأكيد الدفع وتفعيل الباقة
                  </>
                )}
              </button>

              {/* Recovery: payment already charged but activation failed */}
              {showRecover && (
                <button
                  type="button"
                  className="link-checkout__submit-btn link-checkout__submit-btn--recover"
                  disabled={recoverMutation.isPending}
                  onClick={() => recoverMutation.mutate()}
                >
                  {recoverMutation.isPending ? (
                    <>
                      <Loader2 size={18} className="spin" />
                      جاري التحقق من الدفع واستكمال التفعيل…
                    </>
                  ) : (
                    <>
                      <ShieldCheck size={18} />
                      دفعت ولم تُفعّل الباقة؟ استكمال التفعيل بدون خصم جديد
                    </>
                  )}
                </button>
              )}
            </div>
          )}

          {/* ══════════════════════════════════════════════
              VIEW 4: SUCCESS CONFIRMATION
             ══════════════════════════════════════════════ */}
          {step === 'success' && (
            <div className="link-checkout link-checkout--success">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', damping: 15, stiffness: 200 }}
                className="link-checkout__success-icon"
              >
                <CheckCircle2 size={56} />
              </motion.div>
              <h2>تم تفعيل الاشتراك بنجاح!</h2>
              <p>
                تهانينا! تم تفعيل <strong>{customPlanCtx?.name || selectedPlan?.name || 'الباقة الجديدة'}</strong> وتم تحديث كافة الصلاحيات والحدود المتاحة لحسابك.
              </p>
              <div className="link-checkout__success-badge">
                <Sparkles size={16} /> {billingPeriod === 'monthly' ? 'نشط الآن لمدة 30 يوماً' : 'نشط الآن لمدة 12 شهراً'}
              </div>
            </div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
