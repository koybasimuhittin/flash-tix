import hashlib
import json
import time
from pathlib import Path

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from jwt.algorithms import RSAAlgorithm

from auth_svc.schemas import MAX_PASSWORD_BYTES

# bcrypt is deliberately slow (2^rounds iterations) and CPU-bound: callers must run these
# functions in a threadpool so a login storm doesn't freeze the event loop.


def hash_password(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def check_password(password: str, password_hash: str) -> bool:
    encoded = password.encode()
    if len(encoded) > MAX_PASSWORD_BYTES:  # can't have been registered; bcrypt 5 would raise
        return False
    return bcrypt.checkpw(encoded, password_hash.encode())


class TokenIssuer:
    """Signs access tokens with the private key. Other services verify them with the public
    key (flashtix_common.security.TokenVerifier) without calling auth-service."""

    def __init__(self, private_key_pem: bytes, issuer: str, audience: str, ttl_seconds: int):
        self._private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        public_key = self._private_key.public_key()
        public_der = public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        # Key id: lets verifiers pick the right key once keys are rotated.
        self.kid = hashlib.sha256(public_der).hexdigest()[:16]
        self._jwk = {
            **json.loads(RSAAlgorithm.to_jwk(public_key)),
            "kid": self.kid,
            "use": "sig",
            "alg": "RS256",
        }
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_file(cls, path: str, issuer: str, audience: str, ttl_seconds: int) -> "TokenIssuer":
        return cls(Path(path).read_bytes(), issuer, audience, ttl_seconds)

    def issue(self, user_id: int, email: str, name: str, role: str) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": str(user_id),
            "email": email,
            "name": name,
            "role": role,
            "iat": now,
            "exp": now + self.ttl_seconds,
        }
        return jwt.encode(claims, self._private_key, algorithm="RS256", headers={"kid": self.kid})

    def jwks(self) -> dict:
        return {"keys": [self._jwk]}
