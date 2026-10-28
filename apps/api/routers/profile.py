"""A member's note about themselves (members only; a visitor gets the demo
refusal). The chat route reads the same note into the system prompt. The
note is user content: never log it."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import CurrentUser, current_user
from apps.api.demo import refuse_visitor
from apps.api.deps import get_session
from packages.core.schemas.profile import ProfileIn, ProfileOut
from packages.db.repos import profiles as profiles_repo

router = APIRouter(prefix="/me/profile", tags=["profile"])

_VISITOR_REFUSED = {403: {"description": "demo_limit: sign up to keep a note"}}


async def _member(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    # A dependency, not a call in the handler: FastAPI resolves dependencies
    # before it validates the body, so a visitor gets the demo refusal even
    # for a body that would be a 422.
    refuse_visitor(user)
    return user


@router.get("", responses=_VISITOR_REFUSED)
async def get_profile(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_member),
) -> ProfileOut:
    return ProfileOut(about=await profiles_repo.get_about(session, user.id))


@router.put("", responses=_VISITOR_REFUSED)
async def put_profile(
    payload: ProfileIn,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_member),
) -> ProfileOut:
    about = await profiles_repo.set_about(session, user.id, payload.about)
    await session.commit()
    return ProfileOut(about=about)
