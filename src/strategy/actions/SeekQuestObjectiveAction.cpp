/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "SeekQuestObjectiveAction.h"

#include "GameObject.h"
#include "LootObjectStack.h"
#include "Playerbots.h"

bool SeekQuestObjectiveAction::Execute(Event event)
{
    std::vector<QuestObjectiveTarget> targets = AI_VALUE(std::vector<QuestObjectiveTarget>, "quest objective targets");

    if (targets.empty())
    {
        LOG_DEBUG("playerbots", "SeekQuestObjectiveAction: {} has no quest objective targets",
            bot->GetName());
        return false;
    }

    // Find first target within max distance
    for (QuestObjectiveTarget& target : targets)
    {
        if (target.distance > maxSeekDistance)
        {
            LOG_DEBUG("playerbots", "SeekQuestObjectiveAction: {} - target too far ({}y > {}y)",
                bot->GetName(), target.distance, maxSeekDistance);
            continue;
        }

        if (SeekTarget(target))
        {
            Quest const* quest = sObjectMgr->GetQuestTemplate(target.questId);
            std::string questName = quest ? quest->GetTitle() : "Unknown";

            LOG_INFO("playerbots", "SeekQuestObjectiveAction: {} seeking {} for quest '{}' ({}/{}) at {}y",
                bot->GetName(),
                target.IsCreature() ? "creature" : "gameobject",
                questName,
                target.total - target.needed,
                target.total,
                target.distance);

            return true;
        }
    }

    return false;
}

bool SeekQuestObjectiveAction::isUseful()
{
    // Don't seek if in combat
    if (bot->IsInCombat())
        return false;

    // Don't seek if can't move
    if (!AI_VALUE(bool, "can move around"))
        return false;

    // Don't seek if currently flying
    if (bot->HasUnitState(UNIT_STATE_IN_FLIGHT) || bot->IsFlying())
        return false;

    // Don't seek if already moving
    if (bot->isMoving())
        return false;

    // Don't seek if we're already within interaction distance of loot
    // (the loot system can handle it from there)
    LootObject loot = AI_VALUE(LootObject, "loot target");
    if (loot.IsLootPossible(bot))
    {
        float dist = AI_VALUE2(float, "distance", "loot target");
        if (dist < INTERACTION_DISTANCE)
            return false;  // Close enough, loot system can take over
    }

    // Check if we have any quest objectives to seek
    std::vector<QuestObjectiveTarget> targets = AI_VALUE(std::vector<QuestObjectiveTarget>, "quest objective targets");
    if (targets.empty())
        return false;

    // Only useful if at least one target is within range
    for (const QuestObjectiveTarget& target : targets)
    {
        if (target.distance <= maxSeekDistance)
            return true;
    }

    return false;
}

bool SeekQuestObjectiveAction::SeekTarget(QuestObjectiveTarget& target)
{
    if (!target.nearestSpawn)
    {
        LOG_DEBUG("playerbots", "SeekQuestObjectiveAction: {} - no spawn location for target",
            bot->GetName());
        return false;
    }

    // For gameobjects, first try to find an actual spawned GO with matching entry
    if (target.IsGameObject())
    {
        uint32 goEntry = static_cast<uint32>(-target.entry);  // Convert back from negative
        GuidVector gos = AI_VALUE(GuidVector, "nearest game objects");

        // Find the CLOSEST matching GO
        GameObject* closestGo = nullptr;
        float closestDist = 999999.0f;
        ObjectGuid closestGuid;

        for (ObjectGuid const& guid : gos)
        {
            GameObject* go = bot->GetMap()->GetGameObject(guid);
            if (go && go->GetEntry() == goEntry && go->isSpawned())
            {
                float dist = bot->GetDistance(go);
                if (dist < closestDist)
                {
                    closestDist = dist;
                    closestGo = go;
                    closestGuid = guid;
                }
            }
        }

        if (closestGo)
        {
            LOG_INFO("playerbots", "SeekQuestObjectiveAction: {} found closest GO {} at {}y",
                bot->GetName(), closestGo->GetName(), closestDist);

            if (closestDist < 5.0f)  // Close enough to interact
            {
                // Add to loot stack
                LootObjectStack* lootStack = AI_VALUE(LootObjectStack*, "available loot");
                if (lootStack)
                {
                    lootStack->Add(closestGuid);
                }

                // Set as the active loot target so triggers work
                LootObject lootObj(bot, closestGuid);
                context->GetValue<LootObject>("loot target")->Set(lootObj);

                LOG_INFO("playerbots", "SeekQuestObjectiveAction: {} - set GO {} as loot target at {}y",
                    bot->GetName(), closestGo->GetName(), closestDist);

                return false;  // Let loot system take over
            }
            else
            {
                // Move toward the closest game object
                return MoveNear(closestGo, 1.0f);
            }
        }

        LOG_INFO("playerbots", "SeekQuestObjectiveAction: {} - GO entry {} not found in nearby objects, using spawn location",
            bot->GetName(), goEntry);
    }

    // Fall back to spawn position if no actual GO found nearby
    float x = target.nearestSpawn.getX();
    float y = target.nearestSpawn.getY();
    float z = target.nearestSpawn.getZ();
    uint32 mapId = target.nearestSpawn.getMapId();

    // Move towards the spawn location
    if (bot->IsWithinLOS(x, y, z))
    {
        return MoveNear(mapId, x, y, z, INTERACTION_DISTANCE);
    }
    else
    {
        return MoveTo(mapId, x, y, z, false, false);
    }
}
