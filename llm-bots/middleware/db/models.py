"""SQLAlchemy ORM models for acore_llmbots.

Table DDL lives in ``db/migrations/*.sql``; the ORM models here mirror
that schema and are used by the repository layer for CRUD.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LlmSetting(Base):
    """Key-value store for runtime-mutable settings (kill switch, model, etc.)."""

    __tablename__ = "llm_settings"

    key_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PersonalityTemplate(Base):
    """DB-backed personality profile. Overrides on-disk YAML by name."""

    __tablename__ = "personality_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    yaml_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class BuildTemplate(Base):
    """Bot build spec: class / race / spec / level / gear / starting zone."""

    __tablename__ = "build_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    class_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    race_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    spec_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    gear_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="starter"
    )
    starting_zone: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    personality: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ManagedAccount(Base):
    """WoW account created by the middleware (via SOAP ``account create``).

    When ``owner_player_guid`` is set, the account is dedicated to one
    human player (hosts their companion bot characters). NULL means a
    shared/pool account.
    """

    __tablename__ = "managed_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    owner_player_guid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bots: Mapped[list["ManagedBot"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class ManagedBot(Base):
    """Bot character owned by a ManagedAccount."""

    __tablename__ = "managed_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("managed_accounts.id", ondelete="CASCADE"), nullable=False
    )
    character_guid: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    character_name: Mapped[str] = mapped_column(String(12), nullable=False)
    class_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    race_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    build_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("build_templates.id", ondelete="SET NULL"), nullable=True
    )
    personality_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped[ManagedAccount] = relationship(back_populates="bots")


class PlayerBotAssignment(Base):
    """Assignment of a bot character to a specific human player.

    ``party_slot`` 0 is the main party (4 bots matching the player's
    starting zone). Slots 1..7 are the seven secondary parties of 5
    bots each — 39 bots total per fully-assigned player.
    """

    __tablename__ = "player_bot_assignments"
    __table_args__ = (
        UniqueConstraint("player_guid", "bot_guid", name="uq_player_bot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_guid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bot_guid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    party_slot: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    slot_position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlayerSettings(Base):
    """Per-player runtime toggles (bots on/off, LLM on/off)."""

    __tablename__ = "player_settings"

    player_guid: Mapped[int] = mapped_column(Integer, primary_key=True)
    bots_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    llm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
