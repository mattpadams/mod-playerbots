/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "FFAPvpTriggers.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "Playerbots.h"

bool FFAEnemyNearbyTrigger::IsActive()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    Unit* enemy = AI_VALUE(Unit*, "ffa enemy player");
    return enemy != nullptr;
}

bool FFAUnderAttackTrigger::IsActive()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    return AI_VALUE(bool, "ffa under attack");
}

bool FFATerritorialTrigger::IsActive()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    // Only active in territorial mode
    if (sPlayerbotAIConfig->ffaPvpAggressionLevel != 1)
        return false;

    Unit* enemy = AI_VALUE(Unit*, "ffa enemy player");
    if (!enemy)
        return false;

    // Check if enemy is within territorial range
    float range = sPlayerbotAIConfig->ffaPvpTerritorialRange;
    return bot->GetDistance(enemy) <= range;
}

bool FFAAggressiveTrigger::IsActive()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    // Only active in aggressive mode
    if (sPlayerbotAIConfig->ffaPvpAggressionLevel < 2)
        return false;

    Unit* enemy = AI_VALUE(Unit*, "ffa enemy player");
    if (!enemy)
        return false;

    // Check if enemy is within aggressive range
    float range = sPlayerbotAIConfig->ffaPvpAggressiveRange;
    return bot->GetDistance(enemy) <= range;
}

bool FFAOutnumberedTrigger::IsActive()
{
    if (!sPlayerbotAIConfig->ffaPvpEnabled)
        return false;

    uint32 enemyCount = AI_VALUE(uint32, "ffa enemy count");

    // Consider outnumbered if there are 2+ enemies
    // Could be more sophisticated considering group size
    return enemyCount >= 2;
}
