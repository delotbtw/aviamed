from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import TokenPair
from app.core.config import get_settings
from app.core.errors import not_implemented
from app.core.security import create_access_token, new_refresh_token, verify_password
from app.models.system import RefreshToken
from app.repositories.system import RefreshTokenRepository
from app.repositories.user import UserRepository


class InvalidCredentials(Exception):
    """Deliberately generic: do not reveal whether the user exists."""


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    async def login(self, email: str, password: str, user_agent: str | None) -> TokenPair:
        # TODO: rate limit attempts per IP and per account via Redis (settings.login_max_attempts).
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise InvalidCredentials
        s = get_settings()
        raw, token_hash = new_refresh_token()
        await self.tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_ttl_days),
                user_agent=(user_agent or "")[:255] or None,
            )
        )
        user.last_login_at = datetime.now(UTC)
        await self.session.commit()
        return TokenPair(access_token=create_access_token(user.id, user.role), refresh_token=raw)

    async def refresh(self, refresh_token: str) -> TokenPair:
        # TODO: check hash in DB + Redis blacklist, rotate the token.
        raise not_implemented()

    async def logout(self, refresh_token: str) -> None:
        # TODO: set revoked_at and put the hash into the Redis blacklist.
        raise not_implemented()

    async def change_password(self, user_id: int, old: str, new: str) -> None:
        # TODO: verify old, hash new, revoke all active refresh tokens of the user.
        raise not_implemented()
