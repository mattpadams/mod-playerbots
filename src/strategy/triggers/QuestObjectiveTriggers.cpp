/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "QuestObjectiveTriggers.h"

#include "LootObjectStack.h"
#include "Playerbots.h"

bool HasIncompleteQuestObjectiveTrigger::IsActive()
{
    // Don't trigger if in combat
    if (bot->IsInCombat())
        return false;

    // Don't trigger if can't move around
    if (!AI_VALUE(bool, "can move around"))
        return false;

    // Don't trigger if flying
    if (bot->HasUnitState(UNIT_STATE_IN_FLIGHT) || bot->IsFlying())
        return false;

    // Don't trigger if there's loot to grab first
    LootObject loot = AI_VALUE(LootObject, "loot target");
    if (loot.IsLootPossible(bot))
        return false;

    // Check if we have quest objectives within range
    std::vector<QuestObjectiveTarget> targets = AI_VALUE(std::vector<QuestObjectiveTarget>, "quest objective targets");

    if (targets.empty())
        return false;

    // Check if at least one target is within max distance
    for (const QuestObjectiveTarget& target : targets)
    {
        if (target.distance <= maxDistance)
            return true;
    }

    return false;
}

bool ContainerQuestObjectiveNearbyTrigger::IsActive()
{
    // Don't trigger if in combat
    if (bot->IsInCombat())
        return false;

    // Don't trigger if can't move around
    if (!AI_VALUE(bool, "can move around"))
        return false;

    // Don't trigger if flying
    if (bot->HasUnitState(UNIT_STATE_IN_FLIGHT) || bot->IsFlying())
        return false;

    // Check if we have container-only quest objectives within range
    std::vector<ContainerQuestObjective> objectives =
        AI_VALUE(std::vector<ContainerQuestObjective>, "container quest objectives");

    if (objectives.empty())
        return false;

    // Check if nearest container objective is within max distance
    return objectives.front().distance <= maxDistance;
}
