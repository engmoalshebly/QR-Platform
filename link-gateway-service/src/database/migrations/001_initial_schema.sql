-- ============================================
-- Link Gateway Service — Database Schema
-- Run this in Supabase SQL Editor
-- ============================================

-- ══════════════════════════════════════════
-- 1. payments — الجدول الرئيسي للمدفوعات
-- ══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS payments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- الربط بالمنصة الخارجية
    external_order_id       VARCHAR(100),
    external_app_id         VARCHAR(50),

    -- بيانات الدفع
    gateway                 VARCHAR(20) NOT NULL DEFAULT 'LINK',
    payment_method          VARCHAR(30) NOT NULL,
    provider_code           VARCHAR(50) NOT NULL,

    -- المبالغ
    amount                  DECIMAL(18,2) NOT NULL,
    fees                    DECIMAL(18,2) DEFAULT 0,
    commission              DECIMAL(18,2) DEFAULT 0,
    total_amount            DECIMAL(18,2) NOT NULL,
    currency                VARCHAR(5) NOT NULL DEFAULT 'YER',

    -- مصدر الدفع (العميل)
    source_org              VARCHAR(50),
    source_account_type     VARCHAR(30),
    source_account_id       VARCHAR(50),

    -- المستفيد (التاجر)
    beneficiary_org             VARCHAR(50),
    beneficiary_account_type    VARCHAR(30),
    beneficiary_account_id      VARCHAR(50),

    -- الحالة
    status                  VARCHAR(30) NOT NULL DEFAULT 'CREATED',
    failure_reason          TEXT,

    -- الأوقات
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    initiated_at            TIMESTAMPTZ,
    confirmed_at            TIMESTAMPTZ,
    paid_at                 TIMESTAMPTZ,
    failed_at               TIMESTAMPTZ,
    expired_at              TIMESTAMPTZ,

    -- بيانات إضافية
    metadata                JSONB DEFAULT '{}'::jsonb,

    CONSTRAINT chk_payment_status CHECK (status IN (
        'CREATED', 'INITIATING', 'OTP_REQUIRED', 'CONFIRMING',
        'SUCCESS', 'FAILED', 'PENDING', 'CHECKING',
        'EXPIRED', 'CANCELLED', 'UNKNOWN'
    ))
);

CREATE INDEX IF NOT EXISTS idx_payments_external
    ON payments(external_app_id, external_order_id);
CREATE INDEX IF NOT EXISTS idx_payments_status
    ON payments(status);
CREATE INDEX IF NOT EXISTS idx_payments_created
    ON payments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_provider
    ON payments(provider_code);

-- ══════════════════════════════════════════
-- 2. gateway_transactions — سجل عمليات البوابة
-- ══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS gateway_transactions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id                  UUID NOT NULL REFERENCES payments(id) ON DELETE CASCADE,

    -- معلومات العملية
    gateway                     VARCHAR(20) NOT NULL DEFAULT 'LINK',
    operation_type              VARCHAR(30) NOT NULL,

    -- معرفات العميل
    client_request_id           VARCHAR(100) NOT NULL,
    client_reference_number     VARCHAR(30) NOT NULL,

    -- معرفات البوابة
    gateway_request_id          VARCHAR(100),
    gateway_reference_number    VARCHAR(100),

    -- Tokens
    resource_token              VARCHAR(100),
    unified_token               VARCHAR(200),

    -- نتائج العملية
    transaction_id              VARCHAR(100),
    provider_reference          VARCHAR(100),

    -- المبالغ
    amount                      DECIMAL(18,2),
    fees                        DECIMAL(18,2),
    commission                  DECIMAL(18,2),
    currency                    VARCHAR(5),

    -- الاستجابة
    http_status                 INT,
    gateway_success             BOOLEAN,
    response_code               VARCHAR(10),
    response_message            TEXT,
    transaction_status          VARCHAR(30),

    -- التواريخ
    expires_at                  TIMESTAMPTZ,
    transaction_at              TIMESTAMPTZ,
    settlement_at               TIMESTAMPTZ,
    last_status_check_at        TIMESTAMPTZ,

    -- Payloads (مع Mask للبيانات الحساسة)
    request_payload             JSONB,
    response_payload            JSONB,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gw_tx_payment
    ON gateway_transactions(payment_id);
CREATE INDEX IF NOT EXISTS idx_gw_tx_request
    ON gateway_transactions(client_request_id);
CREATE INDEX IF NOT EXISTS idx_gw_tx_ref
    ON gateway_transactions(client_reference_number);
CREATE INDEX IF NOT EXISTS idx_gw_tx_operation
    ON gateway_transactions(operation_type);

-- ══════════════════════════════════════════
-- 3. gateway_providers — كاش بيانات الشركات
-- ══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS gateway_providers (
    id              SERIAL PRIMARY KEY,
    gateway         VARCHAR(20) NOT NULL DEFAULT 'LINK',
    code            VARCHAR(50) NOT NULL,
    name_ar         VARCHAR(100),
    name_en         VARCHAR(100),
    logo_url        TEXT,
    is_active       BOOLEAN DEFAULT true,
    business_type   INT,
    sector_type     VARCHAR(30),
    last_synced_at  TIMESTAMPTZ,

    UNIQUE(gateway, code)
);

-- ══════════════════════════════════════════
-- 4. payment_audit_log — سجل تتبع الحالات
-- ══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS payment_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    payment_id      UUID NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    action          VARCHAR(50) NOT NULL,
    from_status     VARCHAR(30),
    to_status       VARCHAR(30),
    details         JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_payment
    ON payment_audit_log(payment_id);
CREATE INDEX IF NOT EXISTS idx_audit_created
    ON payment_audit_log(created_at DESC);

-- ══════════════════════════════════════════
-- 5. Auto-update updated_at trigger
-- ══════════════════════════════════════════
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE OR REPLACE TRIGGER update_payments_updated_at
    BEFORE UPDATE ON payments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ══════════════════════════════════════════
-- 6. Row Level Security (RLS)
-- ══════════════════════════════════════════
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE gateway_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE gateway_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_audit_log ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service role full access" ON payments
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON gateway_transactions
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON gateway_providers
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON payment_audit_log
    FOR ALL USING (auth.role() = 'service_role');
