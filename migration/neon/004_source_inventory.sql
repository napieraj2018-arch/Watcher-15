-- NEON SHADOW-ONLY: source aggregate inventory, NOT encrypted profiles.
-- Applied in owner staging Neon 28 Oct 2026, no cookies/tokens/UUIDs retained.
-- Source observations are append-only; NEVER use as migration acceptance proof.
CREATE TABLE IF NOT EXISTS aib_shadow_source_inventory (
  observed_at timestamptz PRIMARY KEY,
  source_provider text NOT NULL DEFAULT 'floot' CHECK(source_provider='floot'),
  profiles integer NOT NULL CHECK(profiles>=0),
  archives integer NOT NULL CHECK(archives>=0),
  protected_archives integer NOT NULL CHECK(protected_archives>=0),
  engine_bindings integer NOT NULL CHECK(engine_bindings>=0),
  tasks integer NOT NULL CHECK(tasks>=0),
  source_leases integer NOT NULL CHECK(source_leases>=0),
  unresolved_tasks integer NOT NULL CHECK(unresolved_tasks>=0),
  source_ciphertext_bytes bigint NOT NULL CHECK(source_ciphertext_bytes>=0),
  shadow_writer_enabled boolean NOT NULL DEFAULT false CHECK(NOT shadow_writer_enabled),
  recorded_at timestamptz NOT NULL DEFAULT now()
);
DO $block$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='aib_shadow_source_inventory_immutable') THEN
  CREATE TRIGGER aib_shadow_source_inventory_immutable
    BEFORE UPDATE OR DELETE ON aib_shadow_source_inventory
    FOR EACH ROW EXECUTE FUNCTION aib_shadow_deny_mutation();
 END IF;
END;
$block$;
COMMENT ON TABLE aib_shadow_source_inventory IS
  'Append-only source counts (no credentials, cookies or ciphertext). Not a source/destination equivalence receipt.';
