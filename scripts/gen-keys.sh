#!/usr/bin/env bash
# Creates the local RS256 key pair: auth-service signs JWTs with the private key,
# every service verifies them with the public key. Idempotent: existing keys are kept.
set -euo pipefail

dir="${1:-secrets}"
private="$dir/jwt_private.pem"
public="$dir/jwt_public.pem"

if [[ -f "$private" && -f "$public" ]]; then
  echo "JWT keys already exist in $dir/"
  exit 0
fi

mkdir -p "$dir"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$private" 2>/dev/null
openssl pkey -in "$private" -pubout -out "$public"
# Readable by the non-root container user through the read-only bind mount (local dev keys only).
chmod 644 "$private" "$public"
echo "Created $private and $public"
