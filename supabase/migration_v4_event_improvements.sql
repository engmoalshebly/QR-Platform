-- ============================================================
-- Migration V4: Event System Improvements
-- تحسينات نظام الأحداث بناءً على التقييم الفني
-- ============================================================
-- Changes:
-- 1. Add CHECK constraints to events table
-- 2. Add soft delete to events table
-- 3. Add event_status enum for type safety
-- 4. Add event_assets table
-- 5. Add QR token hash column to invitations (migration from plain text)
-- 6. Add event status workflow function
-- 7. Add capacity fields to events
-- ============================================================

-- ============================================================
-- 1) NEW ENUM: event_status
-- ============================================================

CREATE TYPE event_status AS ENUM ('draft', 'published', 'active', 'completed', 'cancelled');

-- ============================================================
-- 2) ADD EVENT_STATUS TYPE TO EVENTS TABLE
-- ============================================================

-- First, add the new column as TEXT if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'status_new'
    ) THEN
        ALTER TABLE public.events ADD COLUMN status_new TEXT NOT NULL DEFAULT 'draft';
    END IF;
END $$;

-- Migrate existing data
UPDATE public.events SET status_new = status WHERE status_new IS NULL OR status_new = '';

-- Drop old column and rename new one (if status_new exists)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'status_new'
    ) THEN
        ALTER TABLE public.events DROP COLUMN IF EXISTS status;
        ALTER TABLE public.events RENAME COLUMN status_new TO status;
    END IF;
END $$;

-- Change column type to enum (if status is still TEXT)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'status' 
        AND data_type = 'text'
    ) THEN
        -- PostgreSQL does not cast a text DEFAULT while altering the column
        -- type.  Remove it first, convert existing rows explicitly, then set
        -- the enum default back so a blank database can run this migration.
        ALTER TABLE public.events ALTER COLUMN status DROP DEFAULT;
        ALTER TABLE public.events ALTER COLUMN status TYPE event_status USING status::event_status;
        ALTER TABLE public.events ALTER COLUMN status SET DEFAULT 'draft'::event_status;
    END IF;
END $$;

-- ============================================================
-- 3) ADD CHECK CONSTRAINTS TO EVENTS TABLE
-- ============================================================

ALTER TABLE public.events 
    ADD CONSTRAINT check_end_date_after_start 
    CHECK (end_date IS NULL OR end_date >= start_date);

ALTER TABLE public.events 
    ADD CONSTRAINT check_vip_quota_non_negative 
    CHECK (vip_quota >= 0);

ALTER TABLE public.events 
    ADD CONSTRAINT check_normal_quota_non_negative 
    CHECK (normal_quota >= 0);

-- ============================================================
-- 4) ADD SOFT DELETE TO EVENTS TABLE
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'deleted_at'
    ) THEN
        ALTER TABLE public.events ADD COLUMN deleted_at TIMESTAMPTZ;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'deleted_by'
    ) THEN
        ALTER TABLE public.events ADD COLUMN deleted_by UUID REFERENCES public.profiles(id);
    END IF;
END $$;

-- ============================================================
-- 5) ADD CAPACITY FIELDS TO EVENTS TABLE
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'capacity'
    ) THEN
        ALTER TABLE public.events ADD COLUMN capacity INT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'vip_capacity'
    ) THEN
        ALTER TABLE public.events ADD COLUMN vip_capacity INT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'normal_capacity'
    ) THEN
        ALTER TABLE public.events ADD COLUMN normal_capacity INT;
    END IF;
END $$;

-- Add constraint for capacity (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'check_capacity_positive'
    ) THEN
        ALTER TABLE public.events 
        ADD CONSTRAINT check_capacity_positive 
        CHECK (capacity IS NULL OR capacity > 0);
    END IF;
END $$;

-- ============================================================
-- 6) ADD EVENT_ASSETS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.event_assets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id        UUID NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    asset_type      TEXT NOT NULL,  -- cover_image, invitation_design, logo, background, attachment
    file_url        TEXT NOT NULL,
    file_name       TEXT,
    mime_type       TEXT,
    size            BIGINT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    sort_order      INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_assets_event ON public.event_assets(event_id);
CREATE INDEX idx_event_assets_type ON public.event_assets(asset_type);

-- ============================================================
-- 7) ADD QR TOKEN HASH TO INVITATIONS (Security Improvement)
-- ============================================================

-- Add the hash column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'invitations' AND column_name = 'token_hash'
    ) THEN
        ALTER TABLE public.invitations ADD COLUMN token_hash TEXT;
    END IF;
END $$;

-- Generate hashes for existing tokens
UPDATE public.invitations 
SET token_hash = encode(digest(token, 'sha256'), 'hex')
WHERE token_hash IS NULL AND token IS NOT NULL;

-- Add unique constraint on hash (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'invitations_token_hash_unique'
    ) THEN
        ALTER TABLE public.invitations 
        ADD CONSTRAINT invitations_token_hash_unique UNIQUE (token_hash);
    END IF;
END $$;

-- ============================================================
-- 8) ADD EVENT STATUS WORKFLOW FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION public.transition_event_status(
    p_event_id UUID,
    p_new_status event_status,
    p_actor_user_id UUID DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_current_status event_status;
    v_tenant_id UUID;
BEGIN
    -- Get current event status and tenant_id
    SELECT status, tenant_id INTO v_current_status, v_tenant_id
    FROM public.events
    WHERE id = p_event_id;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Event not found';
    END IF;
    
    -- Validate transition based on workflow rules
    CASE v_current_status
        WHEN 'draft' THEN
            IF p_new_status NOT IN ('published', 'cancelled') THEN
                RAISE EXCEPTION 'Invalid transition from draft to %', p_new_status;
            END IF;
            
        WHEN 'published' THEN
            IF p_new_status NOT IN ('active', 'cancelled') THEN
                RAISE EXCEPTION 'Invalid transition from published to %', p_new_status;
            END IF;
            
        WHEN 'active' THEN
            IF p_new_status NOT IN ('completed', 'cancelled') THEN
                RAISE EXCEPTION 'Invalid transition from active to %', p_new_status;
            END IF;
            
        WHEN 'completed' THEN
            IF p_new_status NOT IN ('cancelled') THEN
                RAISE EXCEPTION 'Invalid transition from completed to %', p_new_status;
            END IF;
            
        WHEN 'cancelled' THEN
            RAISE EXCEPTION 'Cannot transition from cancelled status';
            
        ELSE
            RAISE EXCEPTION 'Unknown current status: %', v_current_status;
    END CASE;
    
    -- Update event status
    UPDATE public.events
    SET 
        status = p_new_status,
        updated_at = now()
    WHERE id = p_event_id;
    
    -- Set published_at if transitioning to published
    IF p_new_status = 'published' THEN
        UPDATE public.events
        SET published_at = now()
        WHERE id = p_event_id;
    END IF;
    
    -- Log audit if actor provided
    IF p_actor_user_id IS NOT NULL THEN
        INSERT INTO public.audit_logs (
            tenant_id, actor_user_id, action, resource_type, resource_id, metadata
        ) VALUES (
            v_tenant_id, p_actor_user_id, 'event.status_transition', 'event', p_event_id::TEXT,
            jsonb_build_object(
                'from_status', v_current_status,
                'to_status', p_new_status
            )
        );
    END IF;
    
    RETURN TRUE;
END;
$$;

-- ============================================================
-- 9) UPDATE RLS POLICIES FOR NEW TABLES
-- ============================================================

ALTER TABLE public.event_assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view event assets" ON public.event_assets
    FOR SELECT USING (
        event_id IN (SELECT id FROM public.events WHERE tenant_id IN (SELECT public.get_my_tenant_ids()))
    );

CREATE POLICY "Admins can manage event assets" ON public.event_assets
    FOR ALL USING (
        event_id IN (SELECT id FROM public.events WHERE public.is_admin_of(tenant_id))
    );

-- ============================================================
-- 10) ADD TRIGGER FOR UPDATED_AT ON EVENT_ASSETS
-- ============================================================

CREATE TRIGGER set_updated_at BEFORE UPDATE ON public.event_assets
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ============================================================
-- 11) ADD INDEX FOR DELETED EVENTS
-- ============================================================

CREATE INDEX idx_events_deleted_at ON public.events(deleted_at) WHERE deleted_at IS NOT NULL;

-- ============================================================
-- 12) ADD COMMENTS FOR DOCUMENTATION
-- ============================================================

COMMENT ON COLUMN public.events.deleted_at IS 'Soft delete timestamp. NULL means event is active.';
COMMENT ON COLUMN public.events.deleted_by IS 'User who soft-deleted the event.';
COMMENT ON COLUMN public.events.capacity IS 'Total venue capacity (seats).';
COMMENT ON COLUMN public.events.vip_capacity IS 'VIP seating capacity.';
COMMENT ON COLUMN public.events.normal_capacity IS 'Normal seating capacity.';
COMMENT ON COLUMN public.invitations.token_hash IS 'SHA-256 hash of the QR token for security. Used for verification instead of plain token.';
COMMENT ON FUNCTION public.transition_event_status IS 'Enforces event status workflow transitions with audit logging.';

-- ============================================================
-- END OF MIGRATION V4
-- ============================================================
