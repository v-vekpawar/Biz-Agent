"""User repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.security import hash_password, is_valid_email, normalize_email, MIN_PASSWORD_LENGTH
from ..domain.models import User


class UserRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(self, email: str, password: str, display_name: str) -> User:
        email = normalize_email(email)
        display_name = (display_name or "").strip()
        if not is_valid_email(email):
            raise ValueError("Enter a valid email address.")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > 200:
            raise ValueError("Password is too long.")
        if not display_name or len(display_name) > 100:
            raise ValueError("Name must be 1-100 characters.")
        if self.get_by_email(email) is not None:
            raise ValueError("An account with this email already exists.")
        user = User(email=email, password_hash=hash_password(password), display_name=display_name)
        self._s.add(user)
        try:
            self._s.commit()
        except IntegrityError:
            self._s.rollback()
            raise ValueError("An account with this email already exists.")
        self._s.refresh(user)
        return user

    def get(self, user_id: int) -> User | None:
        return self._s.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._s.scalar(select(User).where(User.email == normalize_email(email)))

    def delete(self, user_id: int) -> bool:
        user = self.get(user_id)
        if user is None:
            return False
        self._s.delete(user)
        self._s.commit()
        return True
