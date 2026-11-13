import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from flashtix_common.security import (
    Principal,
    TokenVerifier,
    get_optional_principal,
    get_principal,
    require_organizer,
)

ISSUER, AUDIENCE = "flashtix-auth", "flashtix"


@pytest.fixture(scope="module")
def keys() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


@pytest.fixture(scope="module")
def client(keys) -> TestClient:
    app = FastAPI()
    app.state.token_verifier = TokenVerifier(keys[1], ISSUER, AUDIENCE)

    @app.get("/me")
    async def me(principal: Principal = Depends(get_principal)) -> dict:
        return {"user_id": principal.user_id, "role": principal.role}

    @app.get("/maybe")
    async def maybe(principal: Principal | None = Depends(get_optional_principal)) -> dict:
        return {"user_id": principal.user_id if principal else None}

    @app.get("/organizer")
    async def organizer(principal: Principal = Depends(require_organizer)) -> dict:
        return {"ok": True}

    return TestClient(app)


def make_token(private_pem: bytes, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "42",
        "email": "a@example.com",
        "name": "A",
        "role": "customer",
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode(claims, private_pem, algorithm="RS256")


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_yields_principal(client, keys):
    response = client.get("/me", headers=auth(make_token(keys[0])))
    assert response.status_code == 200
    assert response.json() == {"user_id": 42, "role": "customer"}


def test_missing_token_is_401(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "NOT_AUTHENTICATED"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 10},
        {"aud": "someone-else"},
        {"iss": "someone-else"},
        {"sub": "not-a-number"},
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "bad-subject"],
)
def test_bad_tokens_are_401(client, keys, overrides):
    response = client.get("/me", headers=auth(make_token(keys[0], **overrides)))
    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "INVALID_TOKEN"}


def test_token_without_role_is_401(client, keys):
    claims = jwt.decode(make_token(keys[0]), options={"verify_signature": False})
    del claims["role"]
    token = jwt.encode(claims, keys[0], algorithm="RS256")
    response = client.get("/me", headers=auth(token))
    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "INVALID_TOKEN"}


def test_token_signed_with_another_key_is_401(client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert client.get("/me", headers=auth(make_token(other_pem))).status_code == 401


def test_optional_principal(client, keys):
    assert client.get("/maybe").json() == {"user_id": None}
    assert client.get("/maybe", headers=auth(make_token(keys[0]))).json() == {"user_id": 42}
    assert client.get("/maybe", headers=auth("garbage")).status_code == 401


def test_require_organizer(client, keys):
    customer = client.get("/organizer", headers=auth(make_token(keys[0])))
    assert customer.status_code == 403
    assert customer.json()["detail"] == {"code": "FORBIDDEN"}
    organizer = client.get("/organizer", headers=auth(make_token(keys[0], role="organizer")))
    assert organizer.status_code == 200
