/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "LootQuestContainerAction.h"

#include "CellImpl.h"
#include "GridNotifiers.h"
#include "GridNotifiersImpl.h"
#include "LootObjectStack.h"
#include "ObjectMgr.h"
#include "Playerbots.h"

bool LootQuestContainerAction::Execute(Event event)
{
    // Get container-only quest objectives
    std::vector<ContainerQuestObjective> objectives =
        AI_VALUE(std::vector<ContainerQuestObjective>, "container quest objectives");

    if (objectives.empty())
    {
        state = ContainerLootState::IDLE;
        return false;
    }

    // Process the nearest objective
    ContainerQuestObjective& objective = objectives.front();

    // Check for enemies near the container
    GuidVector enemies;
    bool hasEnemies = CheckForEnemiesNearContainer(objective, enemies);

    // State machine
    switch (state)
    {
        case ContainerLootState::IDLE:
        case ContainerLootState::SEEKING_CONTAINER:
            if (hasEnemies)
            {
                state = ContainerLootState::ENEMIES_DETECTED;
                return HandleEnemiesDetected(objective);
            }
            return HandleSeekingContainer(objective);

        case ContainerLootState::ENEMIES_DETECTED:
            return HandleEnemiesDetected(objective);

        case ContainerLootState::WAITING_FOR_COMBAT:
            return HandleWaitingForCombat(objective);

        case ContainerLootState::ASSISTING_COMBAT:
            return HandleAssistingCombat();

        case ContainerLootState::LOOTING:
            return HandleLooting(objective);

        default:
            state = ContainerLootState::IDLE;
            return false;
    }
}

bool LootQuestContainerAction::isUseful()
{
    // Don't use if already in combat (unless we're assisting)
    if (bot->IsInCombat() && state != ContainerLootState::ASSISTING_COMBAT)
        return false;

    // Don't use if can't move
    if (!AI_VALUE(bool, "can move around"))
        return false;

    // Don't use if flying
    if (bot->HasUnitState(UNIT_STATE_IN_FLIGHT) || bot->IsFlying())
        return false;

    // Check if we have container-only quest objectives
    std::vector<ContainerQuestObjective> objectives =
        AI_VALUE(std::vector<ContainerQuestObjective>, "container quest objectives");

    if (objectives.empty())
        return false;

    // Check if nearest is within range
    return objectives.front().distance <= CONTAINER_DETECTION_RANGE;
}

bool LootQuestContainerAction::CheckForEnemiesNearContainer(
    ContainerQuestObjective& objective, GuidVector& outEnemies)
{
    outEnemies.clear();

    // Get container position
    float containerX, containerY, containerZ;

    if (objective.nearestContainerGuid)
    {
        GameObject* go = bot->GetMap()->GetGameObject(objective.nearestContainerGuid);
        if (go)
        {
            containerX = go->GetPositionX();
            containerY = go->GetPositionY();
            containerZ = go->GetPositionZ();
        }
        else
        {
            return false;
        }
    }
    else if (objective.nearestSpawn)
    {
        containerX = objective.nearestSpawn.getX();
        containerY = objective.nearestSpawn.getY();
        containerZ = objective.nearestSpawn.getZ();
    }
    else
    {
        return false;
    }

    // Find hostile units within safety radius of container
    std::list<Unit*> units;
    float searchRadius = ENEMY_SAFETY_RADIUS + 20.0f;

    Acore::AnyUnfriendlyUnitInObjectRangeCheck check(bot, bot, searchRadius);
    Acore::UnitListSearcher<Acore::AnyUnfriendlyUnitInObjectRangeCheck> searcher(bot, units, check);
    Cell::VisitObjects(bot, searcher, searchRadius);

    for (Unit* unit : units)
    {
        if (!unit || !unit->IsAlive() || unit->IsPlayer())
            continue;

        if (!unit->IsHostileTo(bot))
            continue;

        // Calculate distance from unit to container position
        float dx = unit->GetPositionX() - containerX;
        float dy = unit->GetPositionY() - containerY;
        float dz = unit->GetPositionZ() - containerZ;
        float distToContainer = std::sqrt(dx*dx + dy*dy + dz*dz);

        if (distToContainer <= ENEMY_SAFETY_RADIUS)
        {
            outEnemies.push_back(unit->GetGUID());
        }
    }

    return !outEnemies.empty();
}

bool LootQuestContainerAction::HandleEnemiesDetected(ContainerQuestObjective& objective)
{
    GuidVector enemies;
    bool hasEnemies = CheckForEnemiesNearContainer(objective, enemies);

    if (!hasEnemies)
    {
        // Enemies are gone - proceed to container
        botAI->TellMaster("The area is clear. Moving to loot the container.");
        state = ContainerLootState::SEEKING_CONTAINER;
        notifiedAboutEnemies = false;
        return HandleSeekingContainer(objective);
    }

    // Notify player if not already notified (with cooldown)
    time_t now = time(nullptr);
    if (!notifiedAboutEnemies || (now - lastNotifyTime) > NOTIFY_COOLDOWN_SECONDS)
    {
        NotifyPlayerAboutEnemies(objective, enemies.size());
        notifiedAboutEnemies = true;
        lastNotifyTime = now;
    }

    // Check if master/player has initiated combat
    if (IsMasterInCombat())
    {
        state = ContainerLootState::ASSISTING_COMBAT;
        return HandleAssistingCombat();
    }

    // Stay in waiting state - don't move
    state = ContainerLootState::WAITING_FOR_COMBAT;
    return true;  // Return true to indicate we're handling the situation
}

void LootQuestContainerAction::NotifyPlayerAboutEnemies(
    ContainerQuestObjective& objective, size_t enemyCount)
{
    Quest const* quest = sObjectMgr->GetQuestTemplate(objective.questId);
    std::string questName = quest ? quest->GetTitle() : "Unknown";

    ItemTemplate const* item = sObjectMgr->GetItemTemplate(objective.itemId);
    std::string itemName = item ? item->Name1 : "quest item";

    std::ostringstream msg;
    msg << "I found a container with " << itemName << " for quest '" << questName << "', ";
    msg << "but there are " << enemyCount << " enemies within " << static_cast<int>(ENEMY_SAFETY_RADIUS) << " yards. ";
    msg << "I'll wait for you to engage them.";

    botAI->TellMaster(msg.str());

    LOG_INFO("playerbots", "LootQuestContainerAction: {} detected {} enemies near container for quest '{}'",
        bot->GetName(), enemyCount, questName);
}

bool LootQuestContainerAction::HandleWaitingForCombat(ContainerQuestObjective& objective)
{
    // Check if enemies are gone
    GuidVector enemies;
    if (!CheckForEnemiesNearContainer(objective, enemies))
    {
        // Area is clear
        botAI->TellMaster("The area is clear. Moving to loot the container.");
        state = ContainerLootState::SEEKING_CONTAINER;
        notifiedAboutEnemies = false;
        return HandleSeekingContainer(objective);
    }

    // Check if master started combat
    if (IsMasterInCombat())
    {
        state = ContainerLootState::ASSISTING_COMBAT;
        return HandleAssistingCombat();
    }

    // Continue waiting - don't move, just stand by
    return true;
}

bool LootQuestContainerAction::IsMasterInCombat()
{
    Player* master = botAI->GetMaster();
    if (master && master->IsInCombat())
        return true;

    // Also check group members
    Group* group = bot->GetGroup();
    if (group)
    {
        for (GroupReference* ref = group->GetFirstMember(); ref; ref = ref->next())
        {
            Player* member = ref->GetSource();
            if (member && member != bot && member->IsInCombat())
                return true;
        }
    }

    return false;
}

bool LootQuestContainerAction::HandleAssistingCombat()
{
    // Bot should now engage in combat alongside the player
    // This is handled by the normal combat strategies

    // Check if combat is over
    if (!bot->IsInCombat() && !IsMasterInCombat())
    {
        // Combat is over - check if area is now clear
        std::vector<ContainerQuestObjective> objectives =
            AI_VALUE(std::vector<ContainerQuestObjective>, "container quest objectives");

        if (!objectives.empty())
        {
            GuidVector enemies;
            if (!CheckForEnemiesNearContainer(objectives.front(), enemies))
            {
                botAI->TellMaster("Combat over. Moving to loot the container.");
                state = ContainerLootState::SEEKING_CONTAINER;
                notifiedAboutEnemies = false;
                return HandleSeekingContainer(objectives.front());
            }
            else
            {
                // Still enemies - go back to waiting
                state = ContainerLootState::WAITING_FOR_COMBAT;
            }
        }
    }

    // Let combat strategies handle the fighting
    // Return false to allow other actions to execute
    return false;
}

bool LootQuestContainerAction::HandleSeekingContainer(ContainerQuestObjective& objective)
{
    if (!objective.nearestContainerGuid)
    {
        // No spawned container - try to move to spawn location
        if (objective.nearestSpawn)
        {
            float x = objective.nearestSpawn.getX();
            float y = objective.nearestSpawn.getY();
            float z = objective.nearestSpawn.getZ();
            uint32 mapId = objective.nearestSpawn.getMapId();

            float dist = bot->GetDistance(x, y, z);
            if (dist < 5.0f)
            {
                // We're at the spawn but container isn't spawned - wait
                LOG_DEBUG("playerbots", "LootQuestContainerAction: {} at container spawn but not spawned yet",
                    bot->GetName());
                return true;
            }

            return MoveNear(mapId, x, y, z, 1.0f);
        }
        return false;
    }

    GameObject* go = bot->GetMap()->GetGameObject(objective.nearestContainerGuid);
    if (!go || !go->isSpawned())
    {
        LOG_DEBUG("playerbots", "LootQuestContainerAction: Container not available");
        return false;
    }

    float dist = bot->GetDistance(go);

    if (dist < 5.0f)  // Close enough to interact
    {
        state = ContainerLootState::LOOTING;
        return HandleLooting(objective);
    }

    // Move toward the container
    return MoveNear(go, 1.0f);
}

bool LootQuestContainerAction::HandleLooting(ContainerQuestObjective& objective)
{
    if (!objective.nearestContainerGuid)
        return false;

    SetLootTarget(objective);

    Quest const* quest = sObjectMgr->GetQuestTemplate(objective.questId);
    std::string questName = quest ? quest->GetTitle() : "Unknown";

    LOG_INFO("playerbots", "LootQuestContainerAction: {} set container as loot target for quest '{}'",
        bot->GetName(), questName);

    // Reset state - the loot system will handle the actual looting
    state = ContainerLootState::IDLE;
    currentTargetContainer.Clear();
    notifiedAboutEnemies = false;

    return false;  // Let loot system take over
}

void LootQuestContainerAction::SetLootTarget(ContainerQuestObjective& objective)
{
    // Add to loot stack
    LootObjectStack* lootStack = AI_VALUE(LootObjectStack*, "available loot");
    if (lootStack)
    {
        lootStack->Add(objective.nearestContainerGuid);
    }

    // Set as the active loot target
    LootObject lootObj(bot, objective.nearestContainerGuid);
    context->GetValue<LootObject>("loot target")->Set(lootObj);
}
