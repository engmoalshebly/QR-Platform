import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, Loader2, AlertCircle, Sparkles, Wallet } from 'lucide-react'
import {
  subscriptionsAPI,
  type Plan,
  type CustomPlanCalculation,
} from '../../settings/api/subscriptionsApi'
import { formatUsd, formatYer } from '@shared/utils/currency'

interface CustomPlanBuilderProps {
  plans: Plan[]
  onBack: () => void
  onReadyToPay: (ctx: { id: string; name: string; totalMonthly: number; totalYearly: number }) => void
}

export function CustomPlanBuilder({ plans, onBack, onReadyToPay }: CustomPlanBuilderProps) {
  const customizablePlans = useMemo(
    () => plans.filter((p) => p.is_customizable && p.code.toLowerCase() !== 'enterprise'),
    [plans],
  )

  const [basePlanCode, setBasePlanCode] = useState<string>(customizablePlans[0]?.code || 'starter')
  const [planName, setPlanName] = useState<string>('باقتي المخصصة')
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [calc, setCalc] = useState<CustomPlanCalculation | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const basePlan = customizablePlans.find((p) => p.code === basePlanCode)
  const baseLimits = useMemo(() => {
    const map: Record<string, number> = {}
    for (const l of basePlan?.limits || []) map[l.key] = l.value
    return map
  }, [basePlan])

  const { data: addons, isLoading: isAddonsLoading } = useQuery({
    queryKey: ['plan-addons'],
    queryFn: subscriptionsAPI.listAddons,
  })

  // Reset quantities to the base plan's included limits when the base changes
  useEffect(() => {
    if (!addons) return
    const initial: Record<string, number> = {}
    for (const addon of addons) {
      const base = baseLimits[addon.key]
      if (base === -1) continue // unlimited in base — nothing to extend
      initial[addon.key] = Math.max(base ?? 0, addon.min_value)
    }
    setQuantities(initial)
  }, [addons, baseLimits])

  // Live price calculation (debounced)
  useEffect(() => {
    if (!addons || !basePlan) return
    const items = addons
      .filter((a) => baseLimits[a.key] !== -1)
      .map((a) => ({ key: a.key, quantity: quantities[a.key] ?? Math.max(baseLimits[a.key] ?? 0, a.min_value) }))

    const timer = setTimeout(async () => {
      try {
        const result = await subscriptionsAPI.calculateCustomPlan(basePlanCode, items, planName)
        setCalc(result)
      } catch {
        // Keep the last successful calculation visible; the error surfaces on submit
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [addons, basePlan, baseLimits, basePlanCode, quantities, planName])

  const createMutation = useMutation({
    mutationFn: async () => {
      if (!addons) throw new Error('العناصر الإضافية غير محملة')
      const items = addons
        .filter((a) => baseLimits[a.key] !== -1)
        .map((a) => ({ key: a.key, quantity: quantities[a.key] ?? Math.max(baseLimits[a.key] ?? 0, a.min_value) }))
      return subscriptionsAPI.createCustomPlan(basePlanCode, items, planName)
    },
    onSuccess: (customPlan) => {
      onReadyToPay({
        id: customPlan.id,
        name: customPlan.name,
        totalMonthly: customPlan.total_price_monthly,
        totalYearly: customPlan.total_price_yearly,
      })
    },
    onError: (err: any) => {
      const msg = err.response?.data?.detail || err.message || 'فشل حفظ الباقة المخصصة.'
      setErrorMessage(msg)
    },
  })

  const setQuantity = (key: string, raw: number, min: number, max: number) => {
    let value = Math.round(raw)
    if (Number.isNaN(value)) value = min
    value = Math.max(min, value)
    if (max > 0) value = Math.min(max, value)
    setQuantities((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <div className="custom-plan-builder">
      <button type="button" className="link-checkout__back-btn" onClick={onBack}>
        <ArrowRight size={16} /> العودة للباقات
      </button>

      <div className="link-checkout__header">
        <div className="link-checkout__icon">
          <Sparkles size={28} />
        </div>
        <h2>صمّم باقتك المخصصة</h2>
        <p>ابدأ من باقة أساسية ثم أضف الموارد التي تحتاجها فقط — السعر يتحدث مباشرة.</p>
      </div>

      {errorMessage && (
        <div className="link-checkout__alert link-checkout__alert--error">
          <AlertCircle size={18} />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Plan name + base plan */}
      <div className="link-checkout__field-group">
        <label className="link-checkout__label" htmlFor="custom-plan-name">اسم الباقة:</label>
        <input
          id="custom-plan-name"
          type="text"
          className="link-checkout__input"
          value={planName}
          onChange={(e) => setPlanName(e.target.value)}
        />
      </div>

      <div className="link-checkout__field-group">
        <label className="link-checkout__label">الباقة الأساسية:</label>
        <div className="custom-plan-builder__base-plans">
          {customizablePlans.map((p) => (
            <button
              key={p.code}
              type="button"
              className={`custom-plan-builder__base-plan ${basePlanCode === p.code ? 'custom-plan-builder__base-plan--active' : ''}`}
              onClick={() => setBasePlanCode(p.code)}
            >
              <strong>{p.name}</strong>
              <span>${formatUsd(p.price_monthly)} / شهر <small>(≈ {formatYer(p.price_monthly)} ر.ي)</small></span>
            </button>
          ))}
        </div>
      </div>

      {/* Addons */}
      {isAddonsLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '24px', color: '#94a3b8' }}>
          <Loader2 size={24} className="spin" />
        </div>
      ) : (
        <div className="custom-plan-builder__addons">
          {(addons || [])
            .filter((a) => baseLimits[a.key] !== -1)
            .map((addon) => {
              const base = baseLimits[addon.key] ?? 0
              const value = quantities[addon.key] ?? Math.max(base, addon.min_value)
              const extra = Math.max(0, value - base)
              return (
                <div key={addon.key} className="custom-plan-builder__addon">
                  <div className="custom-plan-builder__addon-info">
                    <span className="custom-plan-builder__addon-label">
                      {addon.icon} {addon.label_ar}
                    </span>
                    <span className="custom-plan-builder__addon-base">
                      الأساسية تشمل: {base.toLocaleString('en-US')} {addon.unit_ar}
                      {extra > 0 && ` — إضافة: ${extra.toLocaleString('en-US')}`}
                    </span>
                  </div>
                  <div className="custom-plan-builder__addon-controls">
                    <button
                      type="button"
                      onClick={() => setQuantity(addon.key, value - addon.step, Math.max(base, addon.min_value), addon.max_value)}
                    >
                      −
                    </button>
                    <input
                      type="number"
                      dir="ltr"
                      value={value}
                      min={Math.max(base, addon.min_value)}
                      max={addon.max_value > 0 ? addon.max_value : undefined}
                      step={addon.step}
                      onChange={(e) =>
                        setQuantity(addon.key, Number(e.target.value), Math.max(base, addon.min_value), addon.max_value)
                      }
                    />
                    <button
                      type="button"
                      onClick={() => setQuantity(addon.key, value + addon.step, Math.max(base, addon.min_value), addon.max_value)}
                    >
                      +
                    </button>
                  </div>
                </div>
              )
            })}
        </div>
      )}

      {/* Price breakdown */}
      {calc && (
        <div className="custom-plan-builder__summary">
          <div className="custom-plan-builder__summary-row">
            <span>السعر الأساسي ({calc.base_plan_name})</span>
            <strong>${formatUsd(calc.base_price)}</strong>
          </div>
          {calc.addon_lines.map((line) => (
            <div key={line.key} className="custom-plan-builder__summary-row custom-plan-builder__summary-row--addon">
              <span>
                {line.icon} {line.label_ar} (+{line.extra_quantity.toLocaleString('en-US')})
              </span>
              <span>${formatUsd(line.line_total)}</span>
            </div>
          ))}
          <div className="custom-plan-builder__summary-row custom-plan-builder__summary-row--total">
            <span>الإجمالي الشهري</span>
            <strong>${formatUsd(calc.total_monthly)} <small>(≈ {formatYer(calc.total_monthly)} ر.ي)</small></strong>
          </div>
          <div className="custom-plan-builder__summary-row">
            <span>السنوي (خصم شهرين)</span>
            <span>${formatUsd(calc.total_yearly)} <small>(≈ {formatYer(calc.total_yearly)} ر.ي)</small></span>
          </div>
        </div>
      )}

      <button
        type="button"
        className="link-checkout__submit-btn"
        disabled={createMutation.isPending || !calc}
        onClick={() => createMutation.mutate()}
      >
        {createMutation.isPending ? (
          <>
            <Loader2 size={18} className="spin" />
            جاري حفظ الباقة…
          </>
        ) : (
          <>
            <Wallet size={18} />
            حفظ الباقة والمتابعة للدفع
          </>
        )}
      </button>
    </div>
  )
}
