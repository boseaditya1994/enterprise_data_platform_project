-- =============================================================================
-- V1.8__fix_contact_row_access_policy_key_mismatch.sql
-- =============================================================================
-- Fixes the surrogate-key-vs-natural-key mismatch documented in Phase 12
-- Section 6: the original policy attachment on fct_contact compared
-- collector_sk (surrogate) against the policy function's row_collector_id
-- parameter (expects a natural collector_id), which would never match.
--
-- This migration is the concrete answer to "how would you actually ship
-- that documented fix" -- as its own reviewed, versioned change with a
-- clear rollback path, not silently folded back into 08_row_access_policies.sql
-- as if the bug never shipped.

-- Step 1: remove the incorrect policy attachment.
ALTER TABLE MARTS.FCT_CONTACT DROP ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS;

-- Step 2: re-attach correctly. Since fct_contact only carries collector_sk
-- (surrogate), the fix denormalizes collector_id onto the fact at build
-- time (dbt model change, tracked separately in dbt/models/marts/facts/fct_contact.sql
-- git history) rather than joining inside the policy body -- a join inside
-- a row access policy runs on EVERY query against the protected table,
-- so a pre-joined column is both simpler and meaningfully faster at scale.
ALTER TABLE MARTS.FCT_CONTACT
    ADD ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS ON (collector_id);

-- Rollback (manual, not schemachange-automated -- see migrations/README.md):
--   ALTER TABLE MARTS.FCT_CONTACT DROP ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS;
--   ALTER TABLE MARTS.FCT_CONTACT ADD ROW ACCESS POLICY QUARANTINE.RAP_COLLECTOR_OWN_ACCOUNTS ON (collector_sk);
--   -- (restores the original, KNOWN-BROKEN state -- only for emergency
--   -- rollback if V1.8 itself introduces a different regression; the
--   -- correct forward fix is always preferred over reverting to a
--   -- documented bug.)
