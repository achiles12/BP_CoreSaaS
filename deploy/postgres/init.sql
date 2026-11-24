-- Postgres first-start initialisation for the core SaaS scaffold.
--
-- Mounted into /docker-entrypoint-initdb.d/ and executed ONLY when the pgdata
-- volume is empty (first `make up`). It runs against POSTGRES_DB.
-- To re-run on an existing volume:
--   docker compose exec postgres psql -U app -d app -f /docker-entrypoint-initdb.d/init.sql
-- or reset everything with `make clean` (destroys all data).

-- Trigram similarity for typo-tolerant search (similarity(), GIN gin_trgm_ops).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Case-insensitive text for users.email and organizations.slug.
CREATE EXTENSION IF NOT EXISTS citext;
