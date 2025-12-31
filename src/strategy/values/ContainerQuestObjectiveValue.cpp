/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "ContainerQuestObjectiveValue.h"

#include "CellImpl.h"
#include "GridNotifiers.h"
#include "GridNotifiersImpl.h"
#include "LootMgr.h"
#include "LootValues.h"
#include "ObjectMgr.h"
#include "Playerbots.h"

std::vector<ContainerQuestObjective> ContainerQuestObjectivesValue::Calculate()
{
    std::vector<ContainerQuestObjective> objectives;

    if (!bot)
        return objectives;

    // Iterate through bot's quest log
    for (uint8 slot = 0; slot < MAX_QUEST_LOG_SIZE; ++slot)
    {
        uint32 questId = bot->GetQuestSlotQuestId(slot);
        if (!questId)
            continue;

        QuestStatusData& qData = bot->getQuestStatusMap()[questId];
        if (qData.Status != QUEST_STATUS_INCOMPLETE)
            continue;

        Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
        if (!quest)
            continue;

        // Check item objectives
        for (uint32 i = 0; i < QUEST_ITEM_OBJECTIVES_COUNT; ++i)
        {
            uint32 itemId = quest->RequiredItemId[i];
            uint32 reqCount = quest->RequiredItemCount[i];
            if (!itemId || !reqCount)
                continue;

            uint32 hasCount = qData.ItemCount[i];
            if (hasCount >= reqCount)
                continue;

            // Find all drop sources for this item
            std::vector<int32> sources;
            if (!IsContainerOnlyItem(itemId, sources))
                continue;

            // This is a container-only item - find nearest containers
            for (int32 source : sources)
            {
                if (source >= 0)  // Skip creatures (shouldn't happen but safety check)
                    continue;

                uint32 goEntry = static_cast<uint32>(-source);

                // First try to find a spawned container nearby
                float spawnedDistance = 0;
                ObjectGuid containerGuid = FindNearestSpawnedContainer(goEntry, maxDistance, spawnedDistance);

                // Also find the spawn point for fallback
                float spawnDistance = 0;
                GuidPosition spawnPos = FindNearestContainerSpawn(goEntry, spawnDistance);

                // Use whichever is closer
                float effectiveDistance = containerGuid ? spawnedDistance : spawnDistance;

                if (effectiveDistance > maxDistance)
                    continue;  // Too far

                ContainerQuestObjective obj;
                obj.questId = questId;
                obj.objectiveIndex = i;
                obj.containerEntry = goEntry;
                obj.itemId = itemId;
                obj.needed = reqCount - hasCount;
                obj.total = reqCount;
                obj.distance = effectiveDistance;
                obj.nearestSpawn = spawnPos;
                obj.nearestContainerGuid = containerGuid;
                obj.isContainerOnly = true;

                objectives.push_back(obj);

                LOG_DEBUG("playerbots", "ContainerQuestObjectivesValue: Found container objective - quest {}, item {}, GO entry {}, distance {}",
                    questId, itemId, goEntry, effectiveDistance);
            }
        }
    }

    // Sort by distance (nearest first)
    std::sort(objectives.begin(), objectives.end(),
        [](const ContainerQuestObjective& a, const ContainerQuestObjective& b) {
            return a.distance < b.distance;
        });

    return objectives;
}

bool ContainerQuestObjectivesValue::IsContainerOnlyItem(uint32 itemId, std::vector<int32>& outSources)
{
    outSources = FindItemDropSources(itemId);

    if (outSources.empty())
        return false;

    // Check if ALL sources are gameobjects (negative entries)
    for (int32 source : outSources)
    {
        if (source > 0)  // Positive = creature
            return false;
    }

    return true;
}

std::vector<int32> ContainerQuestObjectivesValue::FindItemDropSources(uint32 itemId)
{
    std::vector<int32> sources;

    // Search creature loot tables
    if (CreatureTemplateContainer const* creatures = sObjectMgr->GetCreatureTemplates())
    {
        for (auto const& pair : *creatures)
        {
            uint32 entry = pair.first;
            CreatureTemplate const& info = pair.second;

            if (!info.lootid)
                continue;

            LootTemplate const* lTemplate = LootTemplates_Creature.GetLootFor(info.lootid);
            if (!lTemplate)
                continue;

            LootTemplateAccess const* lTemplateA = reinterpret_cast<LootTemplateAccess const*>(lTemplate);
            for (auto const& lItem : lTemplateA->Entries)
            {
                if (lItem->itemid == itemId)
                {
                    sources.push_back(entry);  // Positive = creature
                    break;
                }
            }
        }
    }

    // Search gameobject loot tables
    if (GameObjectTemplateContainer const* gameobjects = sObjectMgr->GetGameObjectTemplates())
    {
        for (auto const& pair : *gameobjects)
        {
            uint32 entry = pair.first;
            GameObjectTemplate const& info = pair.second;

            if (info.GetLootId() == 0)
                continue;

            LootTemplate const* lTemplate = LootTemplates_Gameobject.GetLootFor(info.GetLootId());
            if (!lTemplate)
                continue;

            LootTemplateAccess const* lTemplateA = reinterpret_cast<LootTemplateAccess const*>(lTemplate);
            for (auto const& lItem : lTemplateA->Entries)
            {
                if (lItem->itemid == itemId)
                {
                    sources.push_back(-static_cast<int32>(entry));  // Negative = gameobject
                    break;
                }
            }
        }
    }

    return sources;
}

ObjectGuid ContainerQuestObjectivesValue::FindNearestSpawnedContainer(uint32 goEntry, float maxRange, float& outDistance)
{
    outDistance = std::numeric_limits<float>::max();
    ObjectGuid nearest;

    GuidVector gos = AI_VALUE(GuidVector, "nearest game objects");

    for (ObjectGuid const& guid : gos)
    {
        GameObject* go = bot->GetMap()->GetGameObject(guid);
        if (!go || go->GetEntry() != goEntry || !go->isSpawned())
            continue;

        float dist = bot->GetDistance(go);
        if (dist < outDistance && dist <= maxRange)
        {
            outDistance = dist;
            nearest = guid;
        }
    }

    return nearest;
}

GuidPosition ContainerQuestObjectivesValue::FindNearestContainerSpawn(uint32 goEntry, float& outDistance)
{
    outDistance = std::numeric_limits<float>::max();
    GuidPosition nearest;

    if (!bot)
        return nearest;

    uint32 botMapId = bot->GetMapId();
    float botX = bot->GetPositionX();
    float botY = bot->GetPositionY();
    float botZ = bot->GetPositionZ();

    for (auto const& pair : sObjectMgr->GetAllGOData())
    {
        GameObjectData const& data = pair.second;
        if (data.id != goEntry)
            continue;

        if (data.mapid != botMapId)
            continue;

        float dx = data.posX - botX;
        float dy = data.posY - botY;
        float dz = data.posZ - botZ;
        float dist = std::sqrt(dx*dx + dy*dy + dz*dz);

        if (dist < outDistance)
        {
            outDistance = dist;
            nearest = GuidPosition(data);
        }
    }

    return nearest;
}

// ContainerLootBlockedValue implementation
bool ContainerLootBlockedValue::Calculate()
{
    GuidVector enemies = AI_VALUE(GuidVector, "enemies near quest container");
    return !enemies.empty();
}

// EnemiesNearQuestContainerValue implementation
GuidVector EnemiesNearQuestContainerValue::Calculate()
{
    GuidVector enemies;

    // Get the nearest container objective
    std::vector<ContainerQuestObjective> objectives =
        AI_VALUE(std::vector<ContainerQuestObjective>, "container quest objectives");

    if (objectives.empty())
        return enemies;

    ContainerQuestObjective& objective = objectives.front();

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
            return enemies;
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
        return enemies;
    }

    // Find hostile units using Cell visitor pattern
    std::list<Unit*> units;
    float searchRadius = enemyRadius + 50.0f;  // Search a bit wider to catch all potential threats

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

        if (distToContainer <= enemyRadius)
        {
            enemies.push_back(unit->GetGUID());
        }
    }

    return enemies;
}
