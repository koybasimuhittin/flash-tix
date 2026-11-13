#!/usr/bin/env bash
# Verifies the database setup against the running compose postgres:
# ownership, per-service isolation, read-only report role, and that the init script reruns cleanly.
set -euo pipefail

set -a; source .env; set +a

fail() { echo "FAIL: $*" >&2; exit 1; }
# psql as a given role over TCP, so password auth is exercised like a real service would. The host
# is the service name, i.e. the container's network address: the image trusts 127.0.0.1 without
# a password, so connecting there would never check one.
as() {
  local user=$1 password=$2 db=$3 sql=$4
  docker compose exec -T -e PGPASSWORD="$password" -e PGOPTIONS="-c client_min_messages=warning" postgres \
    psql -h postgres -U "$user" -d "$db" -v ON_ERROR_STOP=1 -tAc "$sql"
}

if as auth_user "wrong-$RANDOM" authdb "SELECT 1" >/dev/null 2>&1; then
  fail "a wrong password was accepted: password authentication is not being exercised"
fi
echo "ok   password authentication is enforced"

owners=$(as postgres "$POSTGRES_PASSWORD" postgres \
  "SELECT string_agg(datname || ':' || pg_get_userbyid(datdba), ',' ORDER BY datname)
   FROM pg_database WHERE datname IN ('authdb', 'catalogdb', 'bookingdb')")
[[ $owners == "authdb:auth_user,bookingdb:booking_user,catalogdb:catalog_user" ]] \
  || fail "unexpected databases/owners: $owners"
echo "ok   3 databases with their service owners"

as auth_user "$AUTH_DB_PASSWORD" authdb "SELECT 1" >/dev/null || fail "auth_user cannot reach authdb"
if as auth_user "$AUTH_DB_PASSWORD" bookingdb "SELECT 1" >/dev/null 2>&1; then
  fail "auth_user can connect to bookingdb"
fi
if as report_reader "$REPORT_DB_PASSWORD" authdb "SELECT 1" >/dev/null 2>&1; then
  fail "report_reader can connect to authdb"
fi
echo "ok   services are isolated to their own database"

as booking_user "$BOOKING_DB_PASSWORD" bookingdb \
  "DROP TABLE IF EXISTS setup_probe; CREATE TABLE setup_probe (id int); INSERT INTO setup_probe VALUES (1)" \
  >/dev/null
[[ $(as report_reader "$REPORT_DB_PASSWORD" bookingdb "SELECT count(*) FROM setup_probe") == 1 ]] \
  || fail "report_reader cannot read a table booking_user created"
if as report_reader "$REPORT_DB_PASSWORD" bookingdb "INSERT INTO setup_probe VALUES (2)" >/dev/null 2>&1; then
  fail "report_reader can write"
fi
if as report_reader "$REPORT_DB_PASSWORD" bookingdb "CREATE TABLE nope (id int)" >/dev/null 2>&1; then
  fail "report_reader can create tables"
fi
as booking_user "$BOOKING_DB_PASSWORD" bookingdb "DROP TABLE setup_probe" >/dev/null
echo "ok   report_reader can read booking tables but cannot write"

docker compose exec -T postgres /docker-entrypoint-initdb.d/10-init-databases.sh >/dev/null \
  || fail "init script is not idempotent"
echo "ok   init script reruns cleanly"
