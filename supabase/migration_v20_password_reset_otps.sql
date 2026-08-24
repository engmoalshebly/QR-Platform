-- Password reset OTP storage.
CREATE TABLE IF NOT EXISTS public.password_reset_otps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    otp_code TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    blocked_until TIMESTAMPTZ,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    reset_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_password_reset_otps_email
    ON public.password_reset_otps(lower(email), created_at DESC);
CREATE INDEX IF NOT EXISTS idx_password_reset_otps_token
    ON public.password_reset_otps(reset_token)
    WHERE reset_token IS NOT NULL;
