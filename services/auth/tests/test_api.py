"""Endpoint tests against the real local Postgres (`docker compose up -d postgres`).
Skipped when it isn't reachable, e.g. in CI's lint/unit job."""

import asyncio
import json
import os
import socket
import subprocess
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

import auth_svc.routes
from auth_svc.crypto import hash_password

DB_HOST, DB_PORT = "127.0.0.1", 5433
ORGANIZER_EMAIL = "organizer-test@example.com"
ORGANIZER_PASSWORD = "organizer-test-pass"


def _postgres_reachable() -> bool:
    try:
        with socket.create_connection((DB_HOST, DB_PORT), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres on 127.0.0.1:5433 is not running"
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    keys = tmp_path_factory.mktemp("keys")
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
         "-out", str(keys / "private.pem")],
        check=True, capture_output=True,
    )  # fmt: skip
    subprocess.run(
        ["openssl", "pkey", "-in", str(keys / "private.pem"), "-pubout",
         "-out", str(keys / "public.pem")],
        check=True, capture_output=True,
    )  # fmt: skip
    password = os.environ.get("AUTH_DB_PASSWORD", "auth-local")
    with pytest.MonkeyPatch.context() as env:
        env.setenv(
            "AUTH_DATABASE_URL",
            f"postgresql+asyncpg://auth_user:{password}@{DB_HOST}:{DB_PORT}/authdb",
        )
        env.setenv("JWT_PRIVATE_KEY_PATH", str(keys / "private.pem"))
        env.setenv("JWT_PUBLIC_KEY_PATH", str(keys / "public.pem"))
        env.setenv("BCRYPT_ROUNDS", "4")  # fast tests; production uses 12
        env.setenv("BOOTSTRAP_ORGANIZER_EMAIL", ORGANIZER_EMAIL)
        env.setenv("BOOTSTRAP_ORGANIZER_PASSWORD", ORGANIZER_PASSWORD)
        env.setenv("BOOTSTRAP_ORGANIZER_NAME", "Test Organizer")
        from auth_svc.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


def new_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def register(client, email, password="password123", name="Test User"):
    return client.post(
        "/api/auth/register", json={"email": email, "password": password, "name": name}
    )


def login(client, email, password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_register_login_me_flow(client):
    email = new_email()
    created = register(client, email.upper())
    assert created.status_code == 201
    user = created.json()
    assert (user["email"], user["role"]) == (email, "customer")

    logged_in = login(client, email)
    assert logged_in.status_code == 200
    body = logged_in.json()
    assert (body["token_type"], body["expires_in"], body["user"]) == ("bearer", 3600, user)

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == user


def test_duplicate_email_is_409(client):
    email = new_email()
    assert register(client, email).status_code == 201
    duplicate = register(client, email.upper())
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {"code": "EMAIL_TAKEN"}


def test_wrong_password_and_unknown_email_look_the_same(client):
    email = new_email()
    register(client, email)
    wrong_password = login(client, email, "not-the-password")
    unknown_user = login(client, new_email())
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert (
        wrong_password.json() == unknown_user.json() == {"detail": {"code": "INVALID_CREDENTIALS"}}
    )


def test_me_requires_a_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_token_verifies_with_published_jwks(client):
    email = new_email()
    register(client, email)
    token = login(client, email).json()["access_token"]
    (jwk,) = client.get("/api/auth/jwks.json").json()["keys"]
    assert jwt.get_unverified_header(token)["kid"] == jwk["kid"]
    claims = jwt.decode(
        token,
        RSAAlgorithm.from_jwk(json.dumps(jwk)),
        algorithms=["RS256"],
        audience="flashtix",
        issuer="flashtix-auth",
    )
    assert claims["email"] == email


def test_bootstrap_organizer_can_log_in(client):
    response = login(client, ORGANIZER_EMAIL, ORGANIZER_PASSWORD)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "organizer"


def test_bcrypt_runs_off_the_event_loop(client, monkeypatch):
    threads_with_running_loop = []

    def spying_hash(password: str, rounds: int) -> str:
        try:
            asyncio.get_running_loop()
            threads_with_running_loop.append(True)
        except RuntimeError:  # no loop in this thread: we're in the threadpool
            threads_with_running_loop.append(False)
        return hash_password(password, rounds)

    monkeypatch.setattr(auth_svc.routes, "hash_password", spying_hash)
    assert register(client, new_email()).status_code == 201
    assert threads_with_running_loop == [False]


@pytest.mark.parametrize("known_email", [True, False], ids=["known", "unknown"])
def test_login_holds_no_db_connection_during_password_check(client, monkeypatch, known_email):
    email = new_email()
    if known_email:
        assert register(client, email).status_code == 201
    pool = client.app.state.auth.engine.pool
    checked_out_during_check = []
    real_check = auth_svc.routes.check_password

    def spying_check(password: str, password_hash: str) -> bool:
        checked_out_during_check.append(pool.checkedout())
        return real_check(password, password_hash)

    monkeypatch.setattr(auth_svc.routes, "check_password", spying_check)
    login(client, email)
    assert checked_out_during_check == [0]


def test_probes(client):
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"db": "ok"}
