import http from '@services/http/client'

export interface PlanLimit {
  id: string
  plan_id: string
  key: string
  value: number
  period: string
}

export interface Plan {
  id: string
  code: string
  name: string
  description: string
  subtitle: string
  price_monthly: number
  price_yearly: number
  currency: string
  is_active: boolean
  sort_order: number
  badge_color: string
  is_popular: boolean
  is_customizable: boolean
  features: string[]
  limits: PlanLimit[]
}

export interface TenantSubscription {
  id: string
  tenant_id: string
  plan_id: string
  provider: string
  provider_customer_id: string | null
  provider_subscription_id: string | null
  status: string
  cancel_at_period_end: boolean
  current_period_start: string
  current_period_end: string
  canceled_at: string | null
  created_at: string
  updated_at: string
  plan_code: string
  plan_name: string
}

// Payments are verified out of band (bank transfer, cash, etc.) today, not
// through an online gateway. Every request below is reviewed by a platform
// staff member before anything is activated.

export interface SubscriptionRequestResponse {
  request_id: string
  status: 'pending_review'
  message: string
}

export type BillingPeriod = 'monthly' | 'yearly'

// ── Custom Plan Types ──

export interface PlanAddon {
  id: string
  key: string
  label_ar: string
  label_en: string
  unit_ar: string
  unit_en: string
  icon: string
  min_value: number
  max_value: number
  step: number
  price_per_unit: number
  category: string
  sort_order: number
  is_active: boolean
}

export interface CustomPlanItem {
  key: string
  quantity: number
}

export interface AddonLineItem {
  key: string
  label_ar: string
  label_en: string
  icon: string
  base_value: number
  extra_quantity: number
  unit_price: number
  line_total: number
}

export interface CustomPlanCalculation {
  base_plan_code: string
  base_plan_name: string
  base_price: number
  addon_lines: AddonLineItem[]
  addons_total: number
  total_monthly: number
  total_yearly: number
  currency: string
  final_limits: Record<string, number>
}

export interface CustomPlan {
  id: string
  tenant_id: string
  base_plan_id: string | null
  name: string
  addons: Record<string, number>
  base_price: number
  addons_price: number
  total_price_monthly: number
  total_price_yearly: number
  final_limits: Record<string, number>
  status: string
  created_at: string
  updated_at: string
}

export const subscriptionsAPI = {
  listPlans: async (): Promise<Plan[]> => {
    const { data } = await http.get<Plan[]>('/plans')
    return data
  },

  getCurrentSubscription: async (): Promise<TenantSubscription> => {
    const { data } = await http.get<TenantSubscription>('/subscriptions/current')
    return data
  },

  // ── Plan requests (reviewed manually by platform staff) ──

  /**
   * Submit a plan change or renewal request. Nothing activates immediately —
   * a platform staff member reviews it after verifying payment out of band.
   */
  requestSubscription: async (
    planCode: string,
    period: BillingPeriod = 'monthly',
    notes?: string,
  ): Promise<SubscriptionRequestResponse> => {
    const { data } = await http.post<SubscriptionRequestResponse>(
      '/subscriptions/request',
      { plan_code: planCode, period, notes }
    )
    return data
  },

  cancelSubscription: async (): Promise<{ message: string }> => {
    const { data } = await http.post<{ message: string }>('/subscriptions/cancel')
    return data
  },

  // ── Custom Plan Builder ──

  listAddons: async (): Promise<PlanAddon[]> => {
    const { data } = await http.get<PlanAddon[]>('/addons')
    return data
  },

  calculateCustomPlan: async (
    basePlanCode: string,
    items: CustomPlanItem[],
    name?: string,
  ): Promise<CustomPlanCalculation> => {
    const { data } = await http.post<CustomPlanCalculation>(
      '/custom-plans/calculate',
      { base_plan_code: basePlanCode, items, name }
    )
    return data
  },

  createCustomPlan: async (
    basePlanCode: string,
    items: CustomPlanItem[],
    name?: string,
  ): Promise<CustomPlan> => {
    const { data } = await http.post<CustomPlan>(
      '/custom-plans',
      { base_plan_code: basePlanCode, items, name }
    )
    return data
  },

  getActiveCustomPlan: async (): Promise<CustomPlan | null> => {
    try {
      const { data } = await http.get<CustomPlan>('/custom-plans/active')
      return data
    } catch {
      return null
    }
  },

  /**
   * Submit a draft custom plan for staff review. Nothing activates
   * immediately — a platform staff member activates it after verifying
   * payment out of band.
   */
  requestCustomPlanActivation: async (
    customPlanId: string,
    period: BillingPeriod = 'monthly',
    notes?: string,
  ): Promise<SubscriptionRequestResponse> => {
    const { data } = await http.post<SubscriptionRequestResponse>(
      `/custom-plans/${customPlanId}/request`,
      { period, notes }
    )
    return data
  },
}
