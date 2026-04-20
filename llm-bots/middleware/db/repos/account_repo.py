"""Managed WoW account CRUD (managed_accounts)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ManagedAccount


class AccountRepo:
    """CRUD for accounts the middleware has provisioned via SOAP."""

    async def list_all(self, session: AsyncSession) -> list[ManagedAccount]:
        result = await session.execute(
            select(ManagedAccount).order_by(ManagedAccount.username)
        )
        return list(result.scalars())

    async def list_for_player(
        self, session: AsyncSession, player_guid: int
    ) -> list[ManagedAccount]:
        result = await session.execute(
            select(ManagedAccount)
            .where(ManagedAccount.owner_player_guid == player_guid)
            .order_by(ManagedAccount.username)
        )
        return list(result.scalars())

    async def get_by_id(
        self, session: AsyncSession, account_id: int
    ) -> ManagedAccount | None:
        return await session.get(ManagedAccount, account_id)

    async def get_by_username(
        self, session: AsyncSession, username: str
    ) -> ManagedAccount | None:
        result = await session.execute(
            select(ManagedAccount).where(ManagedAccount.username == username)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        username: str,
        owner_player_guid: int | None = None,
        notes: str | None = None,
    ) -> ManagedAccount:
        row = ManagedAccount(
            username=username,
            owner_player_guid=owner_player_guid,
            notes=notes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def delete(self, session: AsyncSession, account_id: int) -> bool:
        row = await self.get_by_id(session, account_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
