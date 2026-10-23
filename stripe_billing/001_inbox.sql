-- Stripe Billing webhook inbox. OFFLINE PostgreSQL 16 proof ONLY.
-- Do not migrate to Floot or Render. No payment, API key or entitlement grants.
BEGIN;
CREATE ROLE aib_stripe_ingest NOLOGIN;
CREATE ROLE aib_stripe_reconciler NOLOGIN;
CREATE SCHEMA stripe_billing;
REVOKE ALL ON SCHEMA stripe_billing FROM PUBLIC;
GRANT USAGE ON SCHEMA stripe_billing TO aib_stripe_ingest,aib_stripe_reconciler;

-- Privileged admin provisions customer-to-tenant mapping after independent
-- Stripe readback; NEVER derive tenant from event.metadata or HTTP request.
CREATE TABLE stripe_billing.customer_tenants(
  livemode boolean NOT NULL,
  customer_id text NOT NULL CHECK(customer_id ~ '^cus_[A-Za-z0-9]{6,120}$'),
  tenant_id uuid NOT NULL,
  enabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(livemode,customer_id)
);

CREATE TABLE stripe_billing.webhook_events(
  livemode boolean NOT NULL,
  event_id text NOT NULL CHECK(event_id ~ '^evt_[A-Za-z0-9]{6,120}$'),
  event_type text NOT NULL CHECK(event_type IN (
    'checkout.session.completed','customer.subscription.created',
    'customer.subscription.updated','customer.subscription.deleted',
    'customer.subscription.paused','customer.subscription.resumed',
    'invoice.paid','invoice.payment_failed',
    'entitlements.active_entitlement_summary.updated'
  )),
  customer_id text,
  object_id text,
  tenant_id uuid,
  body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
  state text NOT NULL CHECK(state IN ('pending_reconcile','unmapped')),
  received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(livemode,event_id),
  CONSTRAINT correct_tenant_state CHECK (
    (state='unmapped' AND tenant_id IS NULL)
    OR (state='pending_reconcile' AND tenant_id IS NOT NULL)
  )
);
CREATE INDEX pending_events_for_reconciliation
  ON stripe_billing.webhook_events(state,received_at)
  WHERE state='pending_reconcile';
REVOKE ALL ON ALL TABLES IN SCHEMA stripe_billing FROM PUBLIC;

-- Public-facing HMAC verifier can ONLY call this function. It does not
-- receive tenant_id, grant a subscription or read the customer table.
CREATE FUNCTION stripe_billing.ingest(
  p_mode boolean,p_event text,p_type text,p_customer text,
  p_object text,p_sha text
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,stripe_billing,pg_temp
AS $body$
DECLARE trusted_tenant uuid;
        old_row stripe_billing.webhook_events%ROWTYPE;
        target_state text;
        inserted integer;
BEGIN
  IF p_mode IS NULL OR p_event IS NULL
    OR p_event !~ '^evt_[A-Za-z0-9]{6,120}$'
    OR p_type IS NULL OR p_type NOT IN (
      'checkout.session.completed','customer.subscription.created',
      'customer.subscription.updated','customer.subscription.deleted',
      'customer.subscription.paused','customer.subscription.resumed',
      'invoice.paid','invoice.payment_failed',
      'entitlements.active_entitlement_summary.updated')
    OR p_sha IS NULL OR p_sha !~ '^[a-f0-9]{64}$'
    OR (p_customer IS NOT NULL AND p_customer !~ '^cus_[A-Za-z0-9]{6,120}$')
    OR (p_object IS NOT NULL AND p_object !~ '^[a-z_]{2,24}_[A-Za-z0-9]{6,120}$')
  THEN RETURN 'invalid'; END IF;

  SELECT m.tenant_id INTO trusted_tenant
    FROM stripe_billing.customer_tenants AS m
    WHERE m.livemode=p_mode AND m.customer_id=p_customer AND m.enabled=true;
  target_state:=CASE WHEN trusted_tenant IS NULL THEN 'unmapped'
                     ELSE 'pending_reconcile' END;
  INSERT INTO stripe_billing.webhook_events(
    livemode,event_id,event_type,customer_id,object_id,tenant_id,body_sha256,state)
  VALUES(p_mode,p_event,p_type,p_customer,p_object,trusted_tenant,p_sha,target_state)
  ON CONFLICT(livemode,event_id) DO NOTHING;
  GET DIAGNOSTICS inserted=ROW_COUNT;
  IF inserted=1 THEN
    RETURN CASE WHEN target_state='pending_reconcile' THEN 'queued' ELSE 'unmapped' END;
  END IF;
  SELECT * INTO old_row FROM stripe_billing.webhook_events AS e
  WHERE e.livemode=p_mode AND e.event_id=p_event;
  IF NOT FOUND THEN RETURN 'unavailable'; END IF;
  IF old_row.body_sha256=p_sha AND old_row.event_type=p_type
     AND old_row.customer_id IS NOT DISTINCT FROM p_customer
     AND old_row.object_id IS NOT DISTINCT FROM p_object
  THEN RETURN 'duplicate'; END IF;
  RETURN 'collision';
END $body$;

REVOKE ALL ON FUNCTION stripe_billing.ingest(boolean,text,text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION stripe_billing.ingest(boolean,text,text,text,text,text)
  TO aib_stripe_ingest;
-- Separate reconciler has read-only access to queued metadata, not writes
-- to tenant mappings, entitlements, Stripe state or cookies.
GRANT SELECT ON stripe_billing.webhook_events TO aib_stripe_reconciler;
COMMIT;
