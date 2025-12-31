/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "FFAEnemyPlayerValue.h"
#include "CellImpl.h"
#include "GridNotifiers.h"
#include "GridNotifiersImpl.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "Playerbots.h"
#include "ServerFacade.h"

Unit* FFAEnemyPlayerValue::Calculate()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return nullptr;

    float range = sPlayerbotAIConfig->ffaPvpAggressiveRange;
    if (sPlayerbotAIConfig->ffaPvpAggressionLevel == 1)
        range = sPlayerbotAIConfig->ffaPvpTerritorialRange;
    else if (sPlayerbotAIConfig->ffaPvpAggressionLevel == 0)
        range = ATTACK_DISTANCE; // For defensive mode, only check nearby

    Unit* result = nullptr;
    float minDistance = range;

    std::list<Unit*> targets;
    Acore::AnyUnitInObjectRangeCheck u_check(bot, range);
    Acore::UnitListSearcher<Acore::AnyUnitInObjectRangeCheck> searcher(bot, targets, u_check);
    Cell::VisitObjects(bot, searcher, range);

    for (Unit* unit : targets)
    {
        if (!AcceptUnit(unit))
            continue;

        float distance = bot->GetDistance(unit);
        if (distance < minDistance)
        {
            minDistance = distance;
            result = unit;
        }
    }

    return result;
}

bool FFAEnemyPlayerValue::AcceptUnit(Unit* unit)
{
    if (!unit || !unit->IsAlive())
        return false;

    Player* player = unit->ToPlayer();
    if (!player)
        return false;

    // Use the IsFFAHostile check from PlayerbotAI
    return botAI->IsFFAHostile(player);
}

uint32 FFAEnemyCountValue::Calculate()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return 0;

    float range = sPlayerbotAIConfig->ffaPvpAggressiveRange;
    if (sPlayerbotAIConfig->ffaPvpAggressionLevel == 1)
        range = sPlayerbotAIConfig->ffaPvpTerritorialRange;
    else if (sPlayerbotAIConfig->ffaPvpAggressionLevel == 0)
        range = ATTACK_DISTANCE;

    uint32 count = 0;

    std::list<Unit*> targets;
    Acore::AnyUnitInObjectRangeCheck u_check(bot, range);
    Acore::UnitListSearcher<Acore::AnyUnitInObjectRangeCheck> searcher(bot, targets, u_check);
    Cell::VisitObjects(bot, searcher, range);

    for (Unit* unit : targets)
    {
        Player* player = unit->ToPlayer();
        if (!player || !player->IsAlive())
            continue;

        if (botAI->IsFFAHostile(player))
            count++;
    }

    return count;
}

bool FFAUnderAttackValue::Calculate()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    // Check if bot is in combat with a player
    if (!bot->IsInCombat())
        return false;

    // Check recent attackers
    // This requires iteration through threat list or combat state
    for (auto const& ref : bot->getAttackers())
    {
        Player* attacker = ref->ToPlayer();
        if (attacker && botAI->IsFFAHostile(attacker))
            return true;
    }

    return false;
}

Unit* FFALastAttackerValue::Calculate()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return nullptr;

    // Find the most recent attacker from combat
    for (auto const& ref : bot->getAttackers())
    {
        Player* attacker = ref->ToPlayer();
        if (attacker && attacker->IsAlive() && botAI->IsFFAHostile(attacker))
            return attacker;
    }

    return nullptr;
}
