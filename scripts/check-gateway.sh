#!/usr/bin/env bash
# Verifies the gateway against the running compose stack on http://localhost:8080:
# health, routing, request-id propagation, the per-user booking rate limit and JSON errors.
# Briefly stops and restarts booking-service to see the gateway's own 502.
set -euo pipefail

base="${GATEWAY_URL:-http://localhost:8080}"

fail() { echo "FAIL: $*" >&2; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
header() { # header <name> <curl args...>: value of a response header (case-insensitive)
  local name=$1; shift
  curl -s -o /dev/null -D - "$@" | tr -d '\r' | awk -v h="$(tr '[:upper:]' '[:lower:]' <<<"$name")" \
    -F': ' 'tolower($1) == h { print $2 }'
}

[[ $(status "$base/gateway/healthz") == 200 ]] || fail "/gateway/healthz is not 200"
echo "ok   gateway health"

[[ $(status "$base/api/events") == 200 ]] || fail "/api/events is not routed to catalog"
[[ $(status "$base/api/auth/jwks.json") == 200 ]] || fail "/api/auth/jwks.json is not routed to auth"
echo "ok   auth and catalog routes"

sent="gateway-check-$RANDOM$RANDOM"
[[ $(header X-Request-ID -H "X-Request-ID: $sent" "$base/api/events") == "$sent" ]] \
  || fail "caller's X-Request-ID is not echoed"
[[ $(header X-Upstream-Request-ID -H "X-Request-ID: $sent" "$base/api/events") == "$sent" ]] \
  || fail "catalog did not receive the caller's X-Request-ID"
generated=$(header X-Request-ID "$base/api/events")
[[ $generated =~ ^[0-9a-f]{32}$ ]] || fail "no generated X-Request-ID (got '$generated')"
[[ $(header X-Upstream-Request-ID "$base/api/events") =~ ^[0-9a-f]{32}$ ]] \
  || fail "generated X-Request-ID is not passed to catalog"
echo "ok   request ids are echoed and reach the service"

long=$(printf 'x%.0s' $(seq 200))
[[ $(header X-Request-ID -H "X-Request-ID: $long" "$base/api/events") =~ ^[0-9a-f]{32}$ ]] \
  || fail "an oversized X-Request-ID was not replaced"
[[ $(header X-Request-ID -H 'X-Request-ID: bad id <script>' "$base/api/events") =~ ^[0-9a-f]{32}$ ]] \
  || fail "an X-Request-ID with unsafe characters was not replaced"
echo "ok   oversized or unsafe request ids are replaced"

is_json_error() { # is_json_error <expected status> <expected code> <response with headers>
  local expected=$1 code=$2 out=$3
  grep -q "^HTTP/[0-9.]* $expected" <<<"$out" || fail "expected $expected, got: $(head -1 <<<"$out")"
  grep -qi '^content-type: application/json' <<<"$out" || fail "$expected is not JSON"
  grep -q "{\"detail\":{\"code\":\"$code\"}}" <<<"$out" || fail "$expected body is not code $code"
}
json_error() { # json_error <expected status> <expected code> <curl args...>
  local expected=$1 code=$2; shift 2
  is_json_error "$expected" "$code" "$(curl -s -D - "$@" | tr -d '\r')"
}

booking=$(status "$base/api/booking/me")
case $booking in
  401) echo "ok   booking route reaches booking-service" ;;
  502)
    json_error 502 UPSTREAM_UNAVAILABLE "$base/api/booking/me"
    echo "ok   booking route answers JSON 502 UPSTREAM_UNAVAILABLE (booking-service not running)"
    ;;
  *) fail "/api/booking/me returned $booking" ;;
esac

burst() { # burst <curl args...>: number of 429s in 30 quick requests
  local n=0
  for _ in $(seq 30); do
    [[ $(status "$@" "$base/api/booking/me") == 429 ]] && n=$((n + 1))
  done
  echo "$n"
}
token="gateway-check-$RANDOM$RANDOM"
limited=$(burst -H "Authorization: Bearer $token")
((limited > 0)) || fail "an authorized burst of 30 got no 429"
# Check the body of a 429 caught mid-burst: a single request after the burst may already be let
# through again, since the bucket refills at the configured rate.
token="gateway-check-$RANDOM$RANDOM"
for _ in $(seq 30); do
  out=$(curl -s -D - -H "Authorization: Bearer $token" "$base/api/booking/me" | tr -d '\r')
  grep -q '^HTTP/[0-9.]* 429' <<<"$out" && break
done
is_json_error 429 RATE_LIMITED "$out"
anonymous=$(burst)
((anonymous == 0)) || fail "anonymous requests were rate-limited ($anonymous x 429)"
echo "ok   per-token rate limit ($limited of 30 limited; anonymous never limited)"

# The gateway's own 502: stop booking-service briefly and expect the JSON error, then restart it.
# Only when the gateway routes to booking-service (not in monolith mode) and booking was up.
upstream=$(docker compose exec -T gateway printenv GATEWAY_BOOKING_UPSTREAM 2>/dev/null || true)
if [[ $booking == 401 && $upstream == booking-service:* ]]; then
  restart() { docker compose up -d --wait --no-deps booking-service >/dev/null 2>&1; }
  trap restart EXIT
  docker compose stop booking-service >/dev/null 2>&1
  json_error 502 UPSTREAM_UNAVAILABLE "$base/api/booking/me"
  restart && trap - EXIT
  # The gateway re-resolves names at most every 10 s (resolver valid=10s), so allow for that.
  for _ in $(seq 15); do [[ $(status "$base/api/booking/me") == 401 ]] && break; sleep 1; done
  [[ $(status "$base/api/booking/me") == 401 ]] || fail "booking route did not recover after restart"
  echo "ok   booking-service stopped → JSON 502 UPSTREAM_UNAVAILABLE; restarted and routed again"
fi
