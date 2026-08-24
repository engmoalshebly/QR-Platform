-- ============================================================
-- Migration v53: سجل مدفوعات الاشتراكات — subscription_payments
-- يحفظ كل عملية دفع ناجحة للاشتراكات (إيصالات + تاريخ فوترة)
-- idempotent: يتعامل مع الجدول إن كان موجوداً من بيئات التطوير القديمة
-- ============================================================

BEGIN;

-- 1. الإنشاء الكامل للبيئات الجديدة
CREATE TABLE IF NOT EXISTS public.subscription_payments (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subscription_id     UUID REFERENCES public.subscriptions(id) ON DELETE SET NULL,
    tenant_id           UUID REFERENCES public.tenants(id) ON DELETE SET NULL,
    link_payment_id     TEXT NOT NULL,
    transaction_id      TEXT,
    amount              NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'YER',
    provider_code       TEXT,
    wallet_number       TEXT,
    period              TEXT NOT NULL DEFAULT 'monthly' CHECK (period IN ('monthly', 'yearly')),
    status              TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed', 'refunded')),
    paid_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- 2. ترقية الجدول إن وُجد من بيئة قديمة (أعمدة + قيود ناقصة)
ALTER TABLE public.subscription_payments ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES public.tenants(id) ON DELETE SET NULL;
ALTER TABLE public.subscription_payments ADD COLUMN IF NOT EXISTS period TEXT NOT NULL DEFAULT 'monthly';
-- subscription_id أصبح يقبل NULL (مدفوعات الباقات المخصصة بلا صف اشتراك)
ALTER TABLE public.subscription_payments ALTER COLUMN subscription_id DROP NOT NULL;

-- 3. فهرسة للاستعلامات الشائعة + منع ازدواج الإيصال عند إعادة المحاولة
CREATE INDEX IF NOT EXISTS idx_subscription_payments_tenant
    ON public.subscription_payments (tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscription_payments_link_payment
    ON public.subscription_payments (link_payment_id);

COMMENT ON TABLE public.subscription_payments IS 'سجل مالي لكل مدفوعات الاشتراكات الناجحة عبر بوابة Link';

-- 4. RLS: القراءة لأعضاء المستأجر فقط (الكتابة عبر service role من الباك إند)
ALTER TABLE public.subscription_payments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "subscription_payments_tenant_read" ON public.subscription_payments;
CREATE POLICY "subscription_payments_tenant_read" ON public.subscription_payments
    FOR SELECT USING (tenant_id IN (
        SELECT m.tenant_id FROM memberships m WHERE m.user_id = auth.uid() AND m.status = 'active'
    ));

COMMIT;
