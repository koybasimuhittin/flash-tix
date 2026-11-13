import hashlib
import json

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from auth_svc.crypto import TokenIssuer, check_password, hash_password
from auth_svc.schemas import LoginIn, RegisterIn
from flashtix_common.security import TokenVerifier


@pytest.fixture(scope="module")
def key_pair() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem


@pytest.fixture(scope="module")
def issuer(key_pair) -> TokenIssuer:
    return TokenIssuer(key_pair[0], "flashtix-auth", "flashtix", ttl_seconds=600)


def test_register_lowercases_email_and_strips_name():
    body = RegisterIn(email="Ada@Example.COM", password="longenough", name="  Ada  ")
    assert body.email == "ada@example.com"
    assert body.name == "Ada"


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "not-an-email", "password": "longenough", "name": "A"},
        {"email": "a@example.com", "password": "short", "name": "A"},
        {"email": "a@example.com", "password": "ü" * 37, "name": "A"},  # 74 bytes
        {"email": "a@example.com", "password": "longenough", "name": "   "},
    ],
    ids=["bad-email", "short-password", "password-over-72-bytes", "blank-name"],
)
def test_register_rejects_invalid_input(fields):
    with pytest.raises(ValidationError):
        RegisterIn(**fields)


def test_login_lowercases_email():
    assert LoginIn(email="Ada@Example.com", password="x").email == "ada@example.com"


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse", rounds=4)
    assert hashed.startswith("$2b$04$")
    assert check_password("correct horse", hashed)
    assert not check_password("wrong horse", hashed)
    assert not check_password("x" * 100, hashed)  # over bcrypt's limit: rejected, not an error


def test_token_has_spec_claims_and_kid(issuer, key_pair):
    token = issuer.issue(7, "a@example.com", "Ada", "organizer")
    header = jwt.get_unverified_header(token)
    public_der = serialization.load_pem_public_key(key_pair[1]).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    assert header["alg"] == "RS256"
    assert header["kid"] == hashlib.sha256(public_der).hexdigest()[:16]

    claims = jwt.decode(token, key_pair[1], algorithms=["RS256"], audience="flashtix")
    assert {k: claims[k] for k in ("iss", "aud", "sub", "email", "name", "role")} == {
        "iss": "flashtix-auth",
        "aud": "flashtix",
        "sub": "7",
        "email": "a@example.com",
        "name": "Ada",
        "role": "organizer",
    }
    assert claims["exp"] - claims["iat"] == 600


def test_token_verifies_with_the_shared_verifier(issuer, key_pair):
    principal = TokenVerifier(key_pair[1], "flashtix-auth", "flashtix").verify(
        issuer.issue(7, "a@example.com", "Ada", "customer")
    )
    assert (principal.user_id, principal.role) == (7, "customer")


def test_jwks_publishes_the_verification_key(issuer):
    (jwk,) = issuer.jwks()["keys"]
    assert (jwk["kid"], jwk["alg"], jwk["use"], jwk["kty"]) == (issuer.kid, "RS256", "sig", "RSA")
    public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
    token = issuer.issue(1, "a@example.com", "A", "customer")
    assert jwt.decode(token, public_key, algorithms=["RS256"], audience="flashtix")["sub"] == "1"
