from dataclasses import dataclass
from pathlib import Path

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    name: str
    role: str


class TokenVerifier:
    """Verifies RS256 tokens issued by auth-service, locally, with its public key.

    Services never call auth-service per request; they only need the public key.
    Create one per process in the lifespan and store it as `app.state.token_verifier`.
    """

    def __init__(self, public_key_pem: str | bytes, issuer: str, audience: str) -> None:
        self._public_key = public_key_pem
        self._issuer = issuer
        self._audience = audience

    @classmethod
    def from_file(cls, path: str, issuer: str, audience: str) -> "TokenVerifier":
        return cls(Path(path).read_bytes(), issuer, audience)

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                # "role" is required so a malformed token fails closed instead of
                # silently getting a default role.
                options={"require": ["exp", "iat", "iss", "aud", "sub", "role"]},
            )
            return Principal(
                user_id=int(claims["sub"]),
                email=claims.get("email", ""),
                name=claims.get("name", ""),
                role=claims["role"],
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise _unauthorized("INVALID_TOKEN") from exc


def _unauthorized(code: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail={"code": code}, headers={"WWW-Authenticate": "Bearer"}
    )


async def get_principal(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Principal:
    """Dependency for endpoints that need a logged-in user. Missing or bad token → 401."""
    if credentials is None:
        raise _unauthorized("NOT_AUTHENTICATED")
    return request.app.state.token_verifier.verify(credentials.credentials)


async def get_optional_principal(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> Principal | None:
    """Like get_principal, but anonymous callers get None. A token that is sent must be valid."""
    if credentials is None:
        return None
    return request.app.state.token_verifier.verify(credentials.credentials)


async def require_organizer(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "organizer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN"})
    return principal
