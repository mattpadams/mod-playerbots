"""Bot character service: SOAP character create + DB bookkeeping.

AzerothCore does not expose a direct GM command that returns a GUID for a
newly-created character. After ``.character create`` we poll
``acore_characters.characters`` for the new name to recover the GUID.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from core.bot_registry import BotRegistry
from core.config import settings
from core.db_client import DbClient
from core.soap_client import SoapClient
from db.engine import session_factory
from db.models import ManagedBot
from db.repos.bot_repo import BotRepo, ManagedBotWrite

if TYPE_CHECKING:
    from bot_agents.agent_supervisor import AgentSupervisor

logger = structlog.get_logger()

# WoW WotLK per-account character cap.
CHAR_LIMIT_PER_ACCOUNT = 10


class BotServiceError(RuntimeError):
    pass


class BotService:
    def __init__(
        self,
        repo: BotRepo,
        soap: SoapClient,
        registry: BotRegistry | None = None,
        db_client: DbClient | None = None,
        supervisor: "AgentSupervisor | None" = None,
    ) -> None:
        self._repo = repo
        self._soap = soap
        self._registry = registry
        self._db = db_client
        self._supervisor = supervisor

    async def list_all(self) -> list[ManagedBot]:
        async with session_factory()() as session:
            return await self._repo.list_all(session)

    async def list_for_account(self, account_id: int) -> list[ManagedBot]:
        async with session_factory()() as session:
            return await self._repo.list_for_account(session, account_id)

    async def count_for_account(self, account_id: int) -> int:
        async with session_factory()() as session:
            return await self._repo.count_for_account(session, account_id)

    async def _lookup_guid_by_name(self, name: str) -> int | None:
        """Poll ``acore_characters`` for a newly-created character GUID."""
        if self._db is None:
            raise BotServiceError(
                "BotService requires a DbClient to resolve new character GUIDs"
            )
        pool = await self._db._pool(settings.db_characters)
        for _ in range(10):  # up to ~5s total
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT guid FROM characters WHERE name = %s LIMIT 1",
                        (name,),
                    )
                    row = await cur.fetchone()
            if row:
                return int(row[0])
            await asyncio.sleep(0.5)
        return None

    async def create(
        self,
        *,
        account_username: str,
        account_id: int,
        character_name: str,
        class_id: int,
        race_id: int,
        level: int = 1,
        build_template_id: int | None = None,
        personality_name: str = "default",
    ) -> ManagedBot:
        if await self.count_for_account(account_id) >= CHAR_LIMIT_PER_ACCOUNT:
            raise BotServiceError(
                f"Account is at the {CHAR_LIMIT_PER_ACCOUNT}-character cap"
            )
        # `.character create <account> <name> <race> <class>` — actual arg
        # order varies between AzerothCore GM extensions; adjust here if
        # the operator's server uses a custom signature.
        response = await self._soap.execute(
            f"character create {account_username} {character_name} "
            f"{race_id} {class_id}"
        )
        if not response.strip():
            raise BotServiceError(
                "SOAP character create returned empty response"
            )
        guid = await self._lookup_guid_by_name(character_name)
        if guid is None:
            # Character was created in WoW but we can't see it — erase
            # the game-side row so the account cap isn't silently burned.
            try:
                await self._soap.execute(f"character erase {character_name}")
            except Exception as rb_exc:
                logger.error(
                    "bot_service.rollback_failed",
                    name=character_name,
                    error=str(rb_exc),
                )
            raise BotServiceError(
                f"Could not resolve GUID for new character '{character_name}'"
            )
        try:
            async with session_factory()() as session:
                row = await self._repo.create(
                    session,
                    ManagedBotWrite(
                        account_id=account_id,
                        character_guid=guid,
                        character_name=character_name,
                        class_id=class_id,
                        race_id=race_id,
                        level=level,
                        build_template_id=build_template_id,
                        personality_name=personality_name,
                    ),
                )
        except Exception:
            try:
                await self._soap.execute(f"character erase {character_name}")
            except Exception as rb_exc:
                logger.error(
                    "bot_service.rollback_failed",
                    name=character_name,
                    error=str(rb_exc),
                )
            raise
        logger.info(
            "bot_service.created",
            guid=guid,
            name=character_name,
            account=account_username,
        )
        return row

    async def delete(self, character_guid: int) -> bool:
        async with session_factory()() as session:
            bot = await self._repo.get_by_guid(session, character_guid)
            if bot is None:
                return False
            name = bot.character_name
        # Demote first so the supervisor stops dispatching events for a
        # character that is about to be erased.
        if self._registry is not None:
            self._registry.demote(character_guid)
        await self._soap.execute(f"character erase {name}")
        async with session_factory()() as session:
            ok = await self._repo.delete(session, character_guid)
        logger.info("bot_service.deleted", guid=character_guid, name=name)
        return ok

    async def set_personality(
        self, character_guid: int, personality: str
    ) -> bool:
        async with session_factory()() as session:
            ok = await self._repo.update_personality(
                session, character_guid, personality
            )
        if not ok:
            return False
        # Hot-swap the live agent's persona so the admin UI's "change
        # personality" edit takes effect immediately. The profile is the
        # same object the running BotAgent holds a reference to, but the
        # agent caches the rendered system prompt — rebuild it.
        if self._registry is not None:
            profile = self._registry.get(character_guid)
            if profile is not None:
                profile.personality = personality
        if self._supervisor is not None:
            agent = self._supervisor.get_agent(character_guid)
            if agent is not None:
                agent.reload_system_prompt()
        return True
