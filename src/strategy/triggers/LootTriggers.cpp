/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "LootTriggers.h"

#include "LootObjectStack.h"
#include "Playerbots.h"
#include "ServerFacade.h"

bool LootAvailableTrigger::IsActive()
{
    bool hasAvailableLoot = AI_VALUE(bool, "has available loot");
    float distance = AI_VALUE2(float, "distance", "loot target");
    bool hasStay = botAI->HasStrategy("stay", BOT_STATE_NON_COMBAT);

    bool distanceCheck = false;
    if (hasStay)
    {
        distanceCheck = sServerFacade->IsDistanceLessOrEqualThan(distance, CONTACT_DISTANCE);
    }
    else
    {
        distanceCheck = sServerFacade->IsDistanceLessOrEqualThan(distance, INTERACTION_DISTANCE - 2.0f);
    }

    bool allTargetsEmpty = AI_VALUE(GuidVector, "all targets").empty();
    return hasAvailableLoot && (distanceCheck || allTargetsEmpty);
}

bool FarFromCurrentLootTrigger::IsActive()
{
    LootObject loot = AI_VALUE(LootObject, "loot target");
    if (loot.IsEmpty())
        return false;

    if (!loot.IsLootPossible(bot))
        return false;

    float distance = AI_VALUE2(float, "distance", "loot target");
    return distance >= INTERACTION_DISTANCE - 2.0f;
}

bool CanLootTrigger::IsActive()
{
    return AI_VALUE(bool, "can loot");
}
