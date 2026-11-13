"""Tiny stdlib-only API client shared by seed.py, smoke_test.py and check_oversell.py.

Talks to the gateway (FLASHTIX_URL, default http://localhost:8080) exactly like the frontend
and Locust do. Settings come from the environment, falling back to the repo's .env file.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("FLASHTIX_URL", "http://localhost:8080").rstrip("/")


def setting(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'")
    return default


def api(
    method: str, path: str, body: dict | None = None, token: str | None = None, timeout: float = 15
) -> tuple[int, object]:
    """Returns (status, parsed JSON or raw bytes). Never raises on HTTP error statuses."""
    request = urllib.request.Request(
        BASE_URL + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
            kind = response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        status, raw, kind = error.code, error.read(), error.headers.get_content_type()
    if kind == "application/json" and raw:
        return status, json.loads(raw)
    return status, raw


def login(email: str, password: str) -> str:
    status, body = api("POST", "/api/auth/login", {"email": email, "password": password})
    if status != 200:
        fail(f"login as {email} failed: {status} {body}")
    return body["access_token"]


def organizer_token() -> str:
    return login(
        setting("BOOTSTRAP_ORGANIZER_EMAIL", "organizer@example.com"),
        setting("BOOTSTRAP_ORGANIZER_PASSWORD", "organizer-local-pass"),
    )


def ok(message: str) -> None:
    print(f"ok    {message}", flush=True)


def fail(message: str) -> None:
    print(f"FAIL  {message}", file=sys.stderr, flush=True)
    sys.exit(1)
