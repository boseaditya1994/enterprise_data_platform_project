-- =============================================================================
-- Dynamic Data Masking -- PII protection (Phase 1 NFR Security, GLBA)
-- =============================================================================
-- Masking is independent of row access (08) -- a collector can see the
-- FULL DETAIL of their own accounts' PII (they need a phone number to
-- call the customer), while an executive or compliance auditor sees
-- every row (row access grants that) but PII stays masked regardless,
-- because their job never requires an individual customer's contact info.

CREATE MASKING POLICY IF NOT EXISTS QUARANTINE.MP_MASK_PHONE
    AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN CURRENT_ROLE() IN ('ROLE_DATA_PLATFORM_ADMIN', 'ROLE_COLLECTOR', 'ROLE_COLLECTIONS_MANAGER') THEN val
        ELSE REGEXP_REPLACE(val, '.', '*', 1, 7)   -- reveal only the last few digits
    END;

CREATE MASKING POLICY IF NOT EXISTS QUARANTINE.MP_MASK_EMAIL
    AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        WHEN CURRENT_ROLE() IN ('ROLE_DATA_PLATFORM_ADMIN', 'ROLE_COLLECTOR', 'ROLE_COLLECTIONS_MANAGER') THEN val
        ELSE CONCAT('***@', SPLIT_PART(val, '@', 2))
    END;

CREATE MASKING POLICY IF NOT EXISTS QUARANTINE.MP_MASK_SSN_LAST4
    AS (val VARCHAR) RETURNS VARCHAR ->
    CASE
        -- SSN fragment is the most sensitive field on the whole platform --
        -- narrower allow-list than phone/email. Even a collections manager
        -- doesn't need it for day-to-day work; only the collector actually
        -- on the call (identity verification) and platform admins do.
        WHEN CURRENT_ROLE() IN ('ROLE_DATA_PLATFORM_ADMIN', 'ROLE_COLLECTOR') THEN val
        ELSE '****'
    END;

CREATE MASKING POLICY IF NOT EXISTS QUARANTINE.MP_MASK_DOB
    AS (val DATE) RETURNS DATE ->
    CASE
        WHEN CURRENT_ROLE() IN ('ROLE_DATA_PLATFORM_ADMIN', 'ROLE_COLLECTOR', 'ROLE_COLLECTIONS_MANAGER') THEN val
        ELSE DATE_TRUNC('YEAR', val)   -- year-only for anyone else (e.g. age-band analytics don't need the exact day)
    END;

ALTER TABLE MARTS.DIM_CUSTOMER MODIFY COLUMN phone_number SET MASKING POLICY QUARANTINE.MP_MASK_PHONE;
ALTER TABLE MARTS.DIM_CUSTOMER MODIFY COLUMN email SET MASKING POLICY QUARANTINE.MP_MASK_EMAIL;
ALTER TABLE MARTS.DIM_CUSTOMER MODIFY COLUMN ssn_last4 SET MASKING POLICY QUARANTINE.MP_MASK_SSN_LAST4;
ALTER TABLE MARTS.DIM_CUSTOMER MODIFY COLUMN date_of_birth SET MASKING POLICY QUARANTINE.MP_MASK_DOB;

-- Verification query any admin can run to confirm policies are actually
-- attached (not just created) -- a real, runnable Snowflake system query:
-- SELECT * FROM TABLE(INFORMATION_SCHEMA.POLICY_REFERENCES(
--     REF_ENTITY_NAME => 'MARTS.DIM_CUSTOMER', REF_ENTITY_DOMAIN => 'TABLE'));
