"""Loot roll arbitration.

When mod-playerbots sees a roll window open on an item eligible for
one or more elevated bots, it POSTs a ``loot_roll_started`` event to
the middleware. ``LootRollHandler.handle()`` runs synchronous
arbitration (no LLM) to pick the winner, issues ``roll pass`` commands
to non-winners immediately, and emits a ``LootRollStartedEvent`` for
the winner so the LLM can decide ``need`` vs ``greed``.

The rule-engine auto-roll behaviour is gated by the ``co +no_loot_roll``
strategy toggle in mod-playerbots (see ``C++ spike`` in DESIGN.md). The
middleware sets that strategy on elevated bots at startup.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from game.commands import BotCommand, CommandType
from game.events import LootRollStartedEvent
from party.arbitration import ArbitrationEngine
from party.gear_scorer import gear_eligible, gear_score
from party.models import RollCandidate

logger = structlog.get_logger()

# Roll windows in WoW last ~60 seconds; we expire our bookkeeping a bit
# sooner so late events on the same item don't collide with a new roll.
ROLL_TTL_SECONDS = 45.0


@dataclass
class _PendingRoll:
    roll_id: str
    item_id: int
    item_link: str
    item_name: str
    candidates: tuple[RollCandidate, ...]
    deadline: float


class LootRollHandler:
    """Synchronous arbitration + dispatch for loot roll windows."""

    def __init__(
        self,
        arbitration: ArbitrationEngine,
        executor,      # CommandExecutor — typed loosely to avoid cycles
    ) -> None:
        self._arb = arbitration
        self._executor = executor
        self._pending: dict[str, _PendingRoll] = {}

    async def handle(
        self,
        roll_id: str,
        item_id: int,
        item_link: str,
        item_name: str,
        candidates: list[RollCandidate],
    ) -> LootRollStartedEvent | None:
        """Run arbitration; dispatch passes; return an event for the winner.

        Returns ``None`` if:
          - no eligible winner exists (all candidates already have
            equal-or-better gear), or
          - this ``roll_id`` was already arbitrated within the TTL
            window (duplicate POST from multiple party bots reaching
            ``LootRollAction::Execute`` in the same tick).
        """
        self._expire_stale()

        if roll_id in self._pending:
            # Duplicate POST for a roll we already resolved. The losers
            # have already been told to pass and the winner event has
            # already been queued — silently ignore.
            logger.debug("loot_roll.duplicate_ignored", roll_id=roll_id)
            return None

        winner = self._arb.pick_winner(
            candidates,
            score_fn=gear_score,
            exclude=lambda c: not gear_eligible(c),
        )

        if winner is None:
            logger.info("loot_roll.no_eligible_winner", roll_id=roll_id, item=item_name)
            return None

        # Tell every other candidate to pass. The winner is NOT told
        # to roll need here — we hand that decision to the LLM so the
        # bot's personality can colour it (need, greed, or pass the
        # upgrade to a needier party member).
        for c in candidates:
            if c.guid == winner.guid:
                continue
            await self._executor.execute(
                BotCommand(
                    command_type=CommandType.LOOT_ROLL,
                    bot_guid=c.guid,
                    payload={"decision": "pass", "item_link": item_link},
                )
            )

        self._pending[roll_id] = _PendingRoll(
            roll_id=roll_id,
            item_id=item_id,
            item_link=item_link,
            item_name=item_name,
            candidates=tuple(candidates),
            deadline=time.monotonic() + ROLL_TTL_SECONDS,
        )

        return LootRollStartedEvent(
            bot_guid=winner.guid,
            bot_name=winner.name,
            roll_id=roll_id,
            item_id=item_id,
            item_link=item_link,
            item_name=item_name,
        )

    def _expire_stale(self) -> None:
        now = time.monotonic()
        stale = [rid for rid, roll in self._pending.items() if roll.deadline < now]
        for rid in stale:
            del self._pending[rid]
