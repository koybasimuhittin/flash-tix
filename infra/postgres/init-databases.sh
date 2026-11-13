#!/usr/bin/env bash
# One database + login role per service, plus a read-only role for the daily report.
# Idempotent: safe to rerun; passwords are (re)set on every run.
#   Local: mounted into /docker-entrypoint-initdb.d/ (runs on the first init of the volume).
#   VM:    can be run by a database VM's startup script as the postgres OS user.
set -euo pipefail

: "${AUTH_DB_PASSWORD:?}" "${CATALOG_DB_PASSWORD:?}" "${BOOKING_DB_PASSWORD:?}" "${REPORT_DB_PASSWORD:?}"

# Passwords travel as psql variables (:'name' quotes them safely); the heredoc itself is literal.
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
  -v auth_pw="$AUTH_DB_PASSWORD" \
  -v catalog_pw="$CATALOG_DB_PASSWORD" \
  -v booking_pw="$BOOKING_DB_PASSWORD" \
  -v report_pw="$REPORT_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', role)
FROM unnest(ARRAY['auth_user', 'catalog_user', 'booking_user', 'report_reader']) AS role
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role)
\gexec

ALTER ROLE auth_user     PASSWORD :'auth_pw';
ALTER ROLE catalog_user  PASSWORD :'catalog_pw';
ALTER ROLE booking_user  PASSWORD :'booking_pw';
ALTER ROLE report_reader PASSWORD :'report_pw';

-- Owning its database lets each service create its own tables in `public` (PG15+).
SELECT format('CREATE DATABASE %I OWNER %I', db, owner)
FROM (VALUES ('authdb', 'auth_user'), ('catalogdb', 'catalog_user'), ('bookingdb', 'booking_user'))
  AS t(db, owner)
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = db)
\gexec

-- Isolation: a service can only connect to its own database.
REVOKE CONNECT ON DATABASE authdb, catalogdb, bookingdb FROM PUBLIC;
GRANT CONNECT ON DATABASE authdb TO auth_user;
GRANT CONNECT ON DATABASE catalogdb TO catalog_user;
GRANT CONNECT ON DATABASE bookingdb TO booking_user, report_reader;

-- Read-only report access, including tables booking-service creates later.
\connect bookingdb
GRANT USAGE ON SCHEMA public TO report_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE booking_user IN SCHEMA public GRANT SELECT ON TABLES TO report_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO report_reader;
SQL
