from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auth_svc.config import AuthSettings
from auth_svc.crypto import TokenIssuer, check_password, hash_password
from auth_svc.models import User
from auth_svc.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from flashtix_common.security import Principal, get_principal


@dataclass
class AuthState:
    """Everything the routes need, created in the lifespan and kept at `app.state.auth`
    (namespaced so the monolith can hold every service's state side by side)."""

    settings: AuthSettings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    issuer: TokenIssuer
    # Hash checked when the email is unknown, so "no such user" takes as long as "wrong
    # password" and response times don't reveal which emails are registered.
    dummy_hash: str


router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_state(request: Request) -> AuthState:
    return request.app.state.auth


async def get_session(state: AuthState = Depends(get_state)) -> AsyncIterator[AsyncSession]:
    async with state.sessionmaker() as session:
        yield session


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(
    body: RegisterIn,
    state: AuthState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
) -> User:
    password_hash = await run_in_threadpool(
        hash_password, body.password, state.settings.bcrypt_rounds
    )
    user = User(email=body.email, name=body.name, password_hash=password_hash, role="customer")
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "EMAIL_TAKEN"}) from exc
    return user


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    state: AuthState = Depends(get_state),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    user = await session.scalar(select(User).where(User.email == body.email))
    # Hand the pooled connection back before the ~250 ms bcrypt check. Holding it (idle in
    # transaction) would cap concurrent logins per pod at the pool size (5 + 5) and turn a
    # login storm into pool waits instead of CPU load. The loaded `user` stays usable.
    await session.close()
    password_hash = user.password_hash if user else state.dummy_hash
    password_ok = await run_in_threadpool(check_password, body.password, password_hash)
    if user is None or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_CREDENTIALS"})
    token = state.issuer.issue(user.id, user.email, user.name, user.role)
    return TokenOut(
        access_token=token,
        expires_in=state.issuer.ttl_seconds,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> User:
    user = await session.get(User, principal.user_id)
    if user is None:  # valid token, but the account no longer exists
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_TOKEN"})
    return user


@router.get("/jwks.json")
async def jwks(state: AuthState = Depends(get_state)) -> dict:
    return state.issuer.jwks()
