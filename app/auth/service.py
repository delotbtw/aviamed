from datetime import UTC, datetime
from typing import NoReturn

from app.audit.service import AuditService
from app.auth.rate_limit import AttemptLimiter, Blocked
from app.auth.schemas import TokenPair
from app.auth.tokens import TokenService
from app.core.exceptions import (
    AuthenticationFailed,
    Conflict,
    InvalidCredentials,
    InvalidInput,
    InvalidOldPassword,
    InvalidRefreshToken,
    RateLimited,
)
from app.core.security import PasswordHasher
from app.core.uow import UnitOfWork
from app.core.validators import check_password_policy, normalize_email
from app.models.user import User
from app.repositories.user import UserRepository


class AuthService:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        tokens: TokenService,
        limiter: AttemptLimiter,
        hasher: PasswordHasher,
        audit: AuditService,
    ) -> None:
        self.uow = uow
        self.users = users
        self.tokens = tokens
        self.limiter = limiter
        self.hasher = hasher
        self.audit = audit

    async def login(self, email: str, password: str, user_agent: str | None, ip: str | None = None) -> TokenPair:
        email = normalize_email(email)

        # One attempt is reserved before the password is checked; a success gives it back.
        blocked = await self.limiter.acquire(email, ip)
        if blocked is not None:
            await self._audit_blocked(None, blocked, ip)
            raise RateLimited(blocked.retry_after)

        # Argon2 runs before any row lock is taken.
        user = await self.users.get_by_email(email)
        if user is None:
            await self.hasher.verify_dummy(password)  # same response time as for an existing account
        verified_hash = user.password_hash if user else None
        if user is None or not await self.hasher.verify(password, user.password_hash) or not user.is_active:
            await self._login_failed(user.id if user else None, ip)

        # Serialize with deactivation / password change / refresh of this user, then re-check under the lock.
        locked = await self.users.get_for_update(user.id)
        if locked is None or not locked.is_active or locked.password_hash != verified_hash:
            await self._login_failed(user.id, ip)
        user = locked

        pair = await self.tokens.issue(user, user_agent)
        user.last_login_at = datetime.now(UTC)
        await self.audit.log(user_id=user.id, action="login_success", ip=ip)
        await self.uow.commit()  # row locks are released here; Redis is touched only afterwards
        await self.limiter.release_success(email, ip)
        return pair

    async def _login_failed(self, user_id: int | None, ip: str | None) -> NoReturn:
        await self.audit.log(user_id=user_id, action="login_failed", ip=ip)
        await self.uow.commit()  # the audit record must survive the failed request
        raise InvalidCredentials

    async def _audit_blocked(self, user_id: int | None, blocked: Blocked, ip: str | None) -> None:
        """One `login_blocked` record per block (when the threshold is crossed), not one per rejected attempt."""
        if blocked.first:
            await self.audit.log(user_id=user_id, action="login_blocked", ip=ip)
            await self.uow.commit()

    async def refresh(self, refresh_token: str, user_agent: str | None = None, ip: str | None = None) -> TokenPair:
        row = await self.tokens.find(refresh_token)
        if row is None:
            raise InvalidRefreshToken
        blacklisted = await self.tokens.is_blacklisted(row)  # Redis call before any row lock is taken
        # Lock order everywhere: users row -> refresh_tokens rows. Re-read the token under the lock.
        user = await self.users.get_for_update(row.user_id)
        row = await self.tokens.find(refresh_token, lock=True)
        if row is None or user is None:
            raise InvalidRefreshToken

        if row.revoked_at is not None or blacklisted:
            # Replay of a rotated/revoked token: assume theft and end every session of the user.
            revoked = await self.tokens.revoke_all(row.user_id)
            if revoked:  # nothing left to revoke means this replay was already handled
                await self.audit.log(user_id=row.user_id, action="token_reuse_detected", ip=ip)
            await self.uow.commit()
            await self.tokens.blacklist_revoked(revoked)
            raise InvalidRefreshToken

        if row.expires_at <= datetime.now(UTC) or not user.is_active:
            raise InvalidRefreshToken

        self.tokens.revoke(row)
        pair = await self.tokens.issue(user, user_agent or row.user_agent)
        await self.audit.log(user_id=user.id, action="token_refresh", ip=ip)
        await self.uow.commit()
        await self.tokens.blacklist_revoked([row])
        return pair

    async def logout(self, refresh_token: str, ip: str | None = None) -> None:
        """Idempotent: unknown or already revoked tokens are silently ignored."""
        row = await self.tokens.find(refresh_token)
        if row is None or row.revoked_at is not None:
            return
        await self.users.get_for_update(row.user_id)  # same lock order as refresh: users -> refresh_tokens
        row = await self.tokens.find(refresh_token, lock=True)
        if row is None or row.revoked_at is not None:
            return
        self.tokens.revoke(row)
        await self.audit.log(user_id=row.user_id, action="logout", ip=ip)
        await self.uow.commit()
        await self.tokens.blacklist_revoked([row])

    async def change_password(self, user: User, old: str, new: str, ip: str | None = None) -> None:
        # Input checks first: rejected inputs must not consume login attempts.
        if new == old:
            raise InvalidInput("New password must differ from the old one")
        try:
            check_password_policy(new, user.email)
        except ValueError as e:
            raise InvalidInput(str(e)) from None

        # Wrong old passwords count towards the same account counter as login (not towards the IP one).
        blocked = await self.limiter.acquire(user.email, ip, count_ip=False)
        if blocked is not None:
            await self._audit_blocked(user.id, blocked, ip)
            raise RateLimited(blocked.retry_after)
        verified_hash = user.password_hash
        if not await self.hasher.verify(old, verified_hash):
            raise InvalidOldPassword
        await self.limiter.release_success(user.email, ip, count_ip=False)
        new_hash = await self.hasher.hash(new)  # Argon2 outside the row lock

        locked = await self.users.get_for_update(user.id)  # serialize with login/refresh/deactivate of this user
        if locked is None or not locked.is_active:
            raise AuthenticationFailed
        if locked.password_hash != verified_hash:
            raise Conflict("Password was changed concurrently, try again")
        locked.password_hash = new_hash
        revoked = await self.tokens.revoke_all(locked.id)
        await self.audit.log(user_id=locked.id, action="password_change", ip=ip)
        await self.uow.commit()
        await self.tokens.blacklist_revoked(revoked)
