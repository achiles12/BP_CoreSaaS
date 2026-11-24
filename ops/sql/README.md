# Operator SQL

There is no admin UI. Use the CLI first (`make cli args=--help`); it validates and writes audit lines. SQL changes made by hand are **not** audited, so keep the statement here for the record.

Rules (`01_design/data_model.md` section 6):

1. Change defaults in `permissions.py` or a migration first, so new tenants get them.
2. For one tenant, run SQL inside a transaction, check the row count, then commit.
3. Never edit `schema_name` or `slug` of an existing organization.

One file per change: `yyyymmdd_<tenant>_<what>.sql`. Start from:

```sql
-- why, who asked, date
BEGIN;
SET LOCAL search_path = tenant_<slug>, public;
-- UPDATE ...
-- SELECT ...   (check)
ROLLBACK;  -- change to COMMIT when the check is right
```

Permission changes are cached: they can take a short while to apply.
