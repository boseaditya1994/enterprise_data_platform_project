# Snowflake Migrations

Uses the [schemachange](https://github.com/Snowflake-Labs/schemachange)
naming convention — `V<version>__<description>.sql` — so DDL changes to
`snowflake/*.sql` (Phase 12) are applied in a tracked, ordered,
idempotent-per-version way rather than someone re-running a full DDL
script by hand against prod and hoping nothing already existed.

## Why this exists separately from `snowflake/*.sql`

Phase 12's numbered files (`01_warehouses.sql` ... `09_masking_policies.sql`)
are the **current-state design documents** — read top to bottom, they
describe the intended final schema. This folder is the **change log** —
each file is one incremental, already-applied-somewhere change, tracked
in `schemachange`'s own metadata table (`METADATA.SCHEMACHANGE_HISTORY`)
so `schemachange deploy` only applies what a given environment hasn't
seen yet. Both exist because they answer different questions: "what
should this look like" (Phase 12) vs. "what changed, when, and has THIS
environment gotten it yet" (here).

## Convention

```
V1.0__initial_warehouses_and_schemas.sql
V1.1__storage_integration.sql
V1.2__external_tables_and_snowpipe.sql
V1.3__streams_and_tasks.sql
V1.4__clustering_and_materialized_views.sql
V1.5__rbac_roles.sql
V1.6__row_access_policies.sql
V1.7__masking_policies.sql
V1.8__fix_contact_row_access_policy_key_mismatch.sql   <- example follow-up fix, see below
```

`V1.0`–`V1.7` are the direct one-to-one migration equivalents of Phase
12's numbered design files (not reproduced again here — same content,
different framing). **`V1.8` is a real example of what this pattern is
FOR**: Phase 12 Section 6 documented a known bug (the `fct_contact` row
access policy compares a surrogate key against a natural key) rather than
silently fixing it. A migration-based deployment is exactly how that
documented fix would actually ship — as its own reviewed, versioned,
independently-deployable change, not folded invisibly back into the
original file.

## Run it

```bash
pip install schemachange
schemachange deploy \
  --config-folder snowflake/migrations \
  --snowflake-account $SNOWFLAKE_ACCOUNT \
  --snowflake-user $SNOWFLAKE_USER \
  --snowflake-role ROLE_DATA_PLATFORM_ADMIN \
  --snowflake-warehouse WH_TRANSFORM \
  --snowflake-database LOAN_DELINQUENCY_CC
```

See `.github/workflows/ci_snowflake_migrations.yml` for how this runs in CI/CD.
