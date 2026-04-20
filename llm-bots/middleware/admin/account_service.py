"""Account service: SOAP ``account create`` + DB bookkeeping."""

from __future__ import annotations

import structlog

from core.bot_registry import BotRegistry
from core.soap_client import SoapClient
from db.engine import session_factory
from db.models import ManagedAccount
from db.repos.account_repo import AccountRepo
from db.repos.bot_repo import BotRepo

logger = structlog.get_logger()


class AccountServiceError(RuntimeError):
    pass


class AccountService:
    """Creates WoW accounts via SOAP and tracks them in acore_llmbots."""

    def __init__(
        self,
        repo: AccountRepo,
        soap: SoapClient,
        bot_repo: BotRepo | None = None,
        registry: BotRegistry | None = None,
    ) -> None:
        self._repo = repo
        self._soap = soap
        self._bot_repo = bot_repo
        self._registry = registry

    async def list_all(self) -> list[ManagedAccount]:
        async with session_factory()() as session:
            return await self._repo.list_all(session)

    async def list_for_player(self, player_guid: int) -> list[ManagedAccount]:
        async with session_factory()() as session:
            return await self._repo.list_for_player(session, player_guid)

    async def create(
        self,
        username: str,
        password: str,
        owner_player_guid: int | None = None,
        notes: str | None = None,
    ) -> ManagedAccount:
        if not username.strip() or not password.strip():
            raise AccountServiceError("Username and password required")
        async with session_factory()() as session:
            if await self._repo.get_by_username(session, username) is not None:
                raise AccountServiceError(
                    f"Account '{username}' already tracked"
                )
        # SOAP account creation. ``.account create <name> <pass>`` is the
        # standard AzerothCore GM command; failures return an empty string
        # from SoapClient because errors are swallowed into logs.
        response = await self._soap.execute(
            f"account create {username} {password}"
        )
        if not response.strip():
            raise AccountServiceError(
                "SOAP account create returned empty response"
            )
        try:
            async with session_factory()() as session:
                row = await self._repo.create(
                    session,
                    username=username,
                    owner_player_guid=owner_player_guid,
                    notes=notes,
                )
        except Exception:
            # DB write failed after the WoW account was created — roll
            # back on the game side so the operator isn't left with an
            # orphan account the middleware doesn't know about.
            try:
                await self._soap.execute(f"account delete {username}")
            except Exception as rb_exc:
                logger.error(
                    "account_service.rollback_failed",
                    username=username,
                    error=str(rb_exc),
                )
            raise
        logger.info(
            "account_service.created",
            username=username,
            owner_player_guid=owner_player_guid,
        )
        return row

    async def delete(self, account_id: int) -> bool:
        """Delete the account via SOAP and drop the bookkeeping row.

        Characters owned by the account are cascade-deleted by the
        ``managed_accounts -> managed_bots`` FK, but any currently-
        elevated agents for those bots still live in memory — demote
        them here so the supervisor stops ticking them.
        """
        async with session_factory()() as session:
            account = await self._repo.get_by_id(session, account_id)
            if account is None:
                return False
            username = account.username
            owned_guids: list[int] = []
            if self._bot_repo is not None:
                owned = await self._bot_repo.list_for_account(session, account_id)
                owned_guids = [b.character_guid for b in owned]
        # Demote running agents BEFORE the SOAP delete so the supervisor
        # stops dispatching events for characters that are about to be
        # erased — otherwise in-flight ticks fire tool calls at GUIDs the
        # server no longer knows about.
        if self._registry is not None:
            for guid in owned_guids:
                self._registry.demote(guid)
        response = await self._soap.execute(f"account delete {username}")
        if response is None:
            raise AccountServiceError("SOAP account delete failed")
        async with session_factory()() as session:
            ok = await self._repo.delete(session, account_id)
        logger.info(
            "account_service.deleted",
            username=username,
            cascaded_bots=len(owned_guids),
        )
        return ok
