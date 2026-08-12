from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime


class Permission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    system_role: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RolePermission(Base):
    __tablename__ = "role_permission"

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("permission.id", ondelete="CASCADE"), primary_key=True
    )


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_account"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username_normalized"),
        CheckConstraint("token_version > 0", name="token_version_positive"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class LoginThrottle(Base):
    __tablename__ = "login_throttle"
    __table_args__ = (CheckConstraint("failed_attempts >= 0", name="failed_attempts_nonnegative"),)

    principal_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    last_failed_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), index=True)


class UserStoreRole(Base):
    __tablename__ = "user_store_role"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), primary_key=True)
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE"), primary_key=True
    )
