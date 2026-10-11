-- Monthly consumption counts every linked workspace under the billing lock.
-- No historical counters are rewritten. Deploy before the updated API.
BEGIN;

INSERT INTO app_schema_migrations (version, name)
VALUES (74, 'usage_accounting_utc')
ON CONFLICT (version) DO NOTHING;

CREATE OR REPLACE FUNCTION public.try_increment_usage(
    p_tenant_id UUID, p_key TEXT, p_amount BIGINT, p_limit BIGINT
) RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_start DATE := date_trunc('month', transaction_timestamp() AT TIME ZONE 'UTC')::date;
    v_used BIGINT;
    v_scope UUID[];
BEGIN
    IF p_amount < 1 OR p_limit < -1 THEN
        RAISE EXCEPTION 'Invalid usage amount or limit';
    END IF;
    -- Caller passes the canonical billing tenant. All linked clients serialize here.
    PERFORM pg_advisory_xact_lock(hashtext('monthly-usage:' || p_tenant_id || ':' || p_key));
    SELECT array_agg(DISTINCT tid) INTO v_scope FROM (
        SELECT p_tenant_id AS tid
        UNION ALL SELECT organizer_tenant_id FROM workspace_links
          WHERE billing_tenant_id=p_tenant_id AND status='active'
        UNION ALL SELECT institution_tenant_id FROM workspace_links
          WHERE billing_tenant_id=p_tenant_id AND status='active'
    ) scope;
    SELECT COALESCE(SUM(value),0) INTO v_used FROM usage_counters
      WHERE tenant_id=ANY(v_scope) AND key=p_key AND period_start=v_start;
    IF p_limit <> -1 AND v_used + p_amount > p_limit THEN
        RETURN NULL;
    END IF;
    INSERT INTO usage_counters AS counter (tenant_id, period_start, period_end, key, value)
      VALUES(p_tenant_id, v_start, (v_start + interval '1 month - 1 day')::date, p_key, p_amount)
      ON CONFLICT (tenant_id, period_start, key) DO UPDATE
      SET value=counter.value + EXCLUDED.value, updated_at=now();
    RETURN v_used + p_amount;
END;
$$;
-- RLS visibility must cover the same billing group as enforcement and display.
CREATE OR REPLACE FUNCTION public.current_linked_tenant_ids() RETURNS UUID[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH billing AS (
    SELECT COALESCE((SELECT billing_tenant_id FROM workspace_links
      WHERE status='active' AND (organizer_tenant_id=public.current_tenant_id()
                              OR institution_tenant_id=public.current_tenant_id()) LIMIT 1),
      public.current_tenant_id()) AS id
  )
  SELECT COALESCE(array_agg(DISTINCT tid) FILTER (WHERE tid IS NOT NULL), ARRAY[]::uuid[])
  FROM (
    SELECT id AS tid FROM billing
    UNION ALL SELECT organizer_tenant_id FROM workspace_links,billing
      WHERE status='active' AND billing_tenant_id=billing.id
    UNION ALL SELECT institution_tenant_id FROM workspace_links,billing
      WHERE status='active' AND billing_tenant_id=billing.id
  ) scope;
$$;
COMMIT;
