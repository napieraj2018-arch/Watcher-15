-- Disposable PostgreSQL 16 only, not any customer account.
\set ON_ERROR_STOP on
CREATE ROLE fixture_stripe_ingest LOGIN IN ROLE aib_stripe_ingest;
CREATE ROLE fixture_stripe_reconciler LOGIN IN ROLE aib_stripe_reconciler;
INSERT INTO stripe_billing.customer_tenants(livemode,customer_id,tenant_id,enabled)
VALUES(false,'cus_111111AAAAAA','11111111-1111-4111-8111-111111111111',true),
      (false,'cus_222222BBBBBB','22222222-2222-4222-8222-222222222222',false);

SET SESSION AUTHORIZATION fixture_stripe_ingest;
DO $test$
DECLARE status text;
BEGIN
  SELECT stripe_billing.ingest(false,'evt_111111AAAAAA','invoice.paid',
    'cus_111111AAAAAA','in_111111AAAAAA',repeat('a',64)) INTO status;
  IF status<>'queued' THEN RAISE EXCEPTION 'KNOWN_CUSTOMER_NOT_QUEUED'; END IF;
  SELECT stripe_billing.ingest(false,'evt_111111AAAAAA','invoice.paid',
    'cus_111111AAAAAA','in_111111AAAAAA',repeat('a',64)) INTO status;
  IF status<>'duplicate' THEN RAISE EXCEPTION 'EVENT_NOT_IDEMPOTENT'; END IF;
  SELECT stripe_billing.ingest(false,'evt_111111AAAAAA','invoice.paid',
    'cus_222222BBBBBB','in_111111AAAAAA',repeat('b',64)) INTO status;
  IF status<>'collision' THEN RAISE EXCEPTION 'EVENT_CONFLICT_NOT_DETECTED'; END IF;
  SELECT stripe_billing.ingest(false,'evt_222222BBBBBB','invoice.payment_failed',
    'cus_222222BBBBBB','in_222222BBBBBB',repeat('b',64)) INTO status;
  IF status<>'unmapped' THEN RAISE EXCEPTION 'DISABLED_CUSTOMER_GRANTED'; END IF;
  SELECT stripe_billing.ingest(false,'evt_333333CCCCCC','customer.subscription.deleted',
    NULL,'sub_333333CCCCCC',repeat('c',64)) INTO status;
  IF status<>'unmapped' THEN RAISE EXCEPTION 'NO_CUSTOMER_GRANTED'; END IF;
  SELECT stripe_billing.ingest(true,'evt_444444DDDDDD','invoice.paid',
    'cus_111111AAAAAA','in_444444DDDDDD',repeat('d',64)) INTO status;
  IF status<>'unmapped' THEN RAISE EXCEPTION 'SANDBOX_LIVE_CROSS_LINK'; END IF;
  SELECT stripe_billing.ingest(false,'evt_BAD','invoice.paid',
    'cus_111111AAAAAA',NULL,repeat('a',64)) INTO status;
  IF status<>'invalid' THEN RAISE EXCEPTION 'INVALID_EVENT_ACCEPTED'; END IF;

  BEGIN
    PERFORM * FROM stripe_billing.customer_tenants;
    RAISE EXCEPTION 'INGRESS_READ_TENANT_BINDINGS';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM * FROM stripe_billing.webhook_events;
    RAISE EXCEPTION 'INGRESS_READ_RAW_EVENT_ROWS';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO stripe_billing.customer_tenants(livemode,customer_id,tenant_id)
    VALUES(false,'cus_999999DDDDDD','33333333-3333-4333-8333-333333333333');
    RAISE EXCEPTION 'INGRESS_BOUND_FOREIGN_CUSTOMER';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $test$;
RESET SESSION AUTHORIZATION;
DO $test$
DECLARE total int; queued int; unmapped int;
BEGIN
  SELECT count(*),count(*) FILTER(WHERE state='pending_reconcile'),
    count(*) FILTER(WHERE state='unmapped')
  INTO total,queued,unmapped FROM stripe_billing.webhook_events;
  IF total<>4 OR queued<>1 OR unmapped<>3
  THEN RAISE EXCEPTION 'INBOX_ISOLATION_COUNTS_BAD'; END IF;
END $test$;
SELECT 'STRIPE_INBOX_SQL_SECURITY_PASS' AS proof;
