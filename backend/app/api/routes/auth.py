"""Account routes: register, sign in, who am I, delete account."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...core import config, security
from ...core.ratelimit import limit
from ...domain.models import User
from ...repositories import UserRepository
from ..deps import get_current_user, get_user_repo
from ..schemas.sprints import LoginIn, RegisterIn, TokenOut, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_out(user: User) -> TokenOut:
    return TokenOut(access_token=security.create_access_token(user.id), user=UserRead.model_validate(user))


@router.post("/register", status_code=201, response_model=TokenOut, dependencies=[Depends(limit("register", 10, 3600))])
def register(payload: RegisterIn, users: UserRepository = Depends(get_user_repo)):
    if not config.allow_registration():
        raise HTTPException(status_code=403, detail="Registration is closed on this server.")
    try:
        user = users.create(payload.email, payload.password, payload.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _token_out(user)


@router.post("/login", response_model=TokenOut, dependencies=[Depends(limit("login", 10, 300))])
def login(payload: LoginIn, users: UserRepository = Depends(get_user_repo)):
    user = users.get_by_email(payload.email)
    # Same error for unknown email and wrong password; verify against a dummy hash
    # when the user is missing so response time doesn't reveal which emails exist.
    stored = user.password_hash if user else _DUMMY_HASH
    ok = security.verify_password(payload.password, stored)
    if not user or not ok:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return _token_out(user)


_DUMMY_HASH = security.hash_password("not-a-real-password")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@router.delete("/me", status_code=204)
def delete_account(user: User = Depends(get_current_user), users: UserRepository = Depends(get_user_repo)):
    """Deletes the account and everything it owns (ideas, sprints, collected signups)."""
    users.delete(user.id)
    return None
