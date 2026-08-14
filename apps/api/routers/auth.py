from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_session
from apps.api.redis_client import get_redis
from packages.core.auth import rate_limit
from packages.core.auth.passwords import hash_password_async
from packages.core.schemas.auth import SignupIn, SignupOut
from packages.db.repos import users as users_repo

router = APIRouter(prefix="/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    # Direct-connect dev value. M3 note (spec): behind the proxy this must come
    # from X-Forwarded-For or every visitor shares one bucket.
    return request.client.host if request.client else "unknown"


@router.post("/signup", status_code=201)
async def signup(
    body: SignupIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SignupOut:
    if not await rate_limit.hit(
        get_redis(), "signup_ip", client_ip(request), limit=10, window_s=3600
    ):
        raise HTTPException(429, detail="too many signups; try again later")
    email = body.email.strip().lower()
    if await users_repo.get_by_email(session, email) is not None:
        # TEMPORARY (slice 1, spec "Slices"): plain error. Slice 4 replaces it
        # with the uniform "check your inbox" + notification email so signup
        # stops being an account-existence oracle.
        raise HTTPException(400, detail="an account with this email already exists")
    user = await users_repo.create_password_user(
        session, email, await hash_password_async(body.password), body.name
    )
    await session.commit()
    return SignupOut(id=user.id, email=user.email)
