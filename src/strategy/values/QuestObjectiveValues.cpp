/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "QuestObjectiveValues.h"

#include "LootMgr.h"
#include "LootValues.h"
#include "ObjectMgr.h"
#include "Playerbots.h"
#include "QuestValues.h"

std::vector<QuestObjectiveTarget> QuestObjectiveTargetsValue::Calculate()
{
    std::vector<QuestObjectiveTarget> targets;

    if (!bot)
        return targets;

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

            uint32 needed = reqCount - hasCount;
            AddItemObjective(targets, questId, i, itemId, needed, reqCount);
        }

        // Check NPC/GO objectives (kills or interactions)
        for (uint32 i = 0; i < QUEST_OBJECTIVES_COUNT; ++i)
        {
            int32 reqNpcOrGo = quest->RequiredNpcOrGo[i];
            uint32 reqCount = quest->RequiredNpcOrGoCount[i];
            if (!reqNpcOrGo || !reqCount)
                continue;

            uint32 hasCount = qData.CreatureOrGOCount[i];
            if (hasCount >= reqCount)
                continue;

            uint32 needed = reqCount - hasCount;
            AddKillObjective(targets, questId, i, reqNpcOrGo, needed, reqCount);
        }
    }

    // Sort by distance (nearest first)
    std::sort(targets.begin(), targets.end(),
        [](const QuestObjectiveTarget& a, const QuestObjectiveTarget& b) {
            return a.distance < b.distance;
        });

    return targets;
}

void QuestObjectiveTargetsValue::AddItemObjective(std::vector<QuestObjectiveTarget>& targets, uint32 questId,
    uint32 objectiveIndex, uint32 itemId, uint32 needed, uint32 total)
{
    // Use direct loot template query instead of GAI_VALUE (avoids crash)
    std::vector<int32> dropSources = FindItemDropSources(itemId);

    if (dropSources.empty())
    {
        LOG_DEBUG("playerbots", "QuestObjectiveTargetsValue: No drop sources found for item {} (quest {})",
            itemId, questId);
        return;
    }

    // Find the nearest source for this item
    float bestDistance = std::numeric_limits<float>::max();
    GuidPosition bestSpawn;
    int32 bestEntry = 0;

    for (int32 entry : dropSources)
    {
        float distance;
        GuidPosition spawn = FindNearestSpawn(entry, distance);

        if (spawn && distance < bestDistance)
        {
            bestDistance = distance;
            bestSpawn = spawn;
            bestEntry = entry;
        }
    }

    if (!bestSpawn)
        return;

    QuestObjectiveTarget target;
    target.questId = questId;
    target.objectiveIndex = objectiveIndex;
    target.entry = bestEntry;
    target.itemId = itemId;
    target.needed = needed;
    target.total = total;
    target.distance = bestDistance;
    target.nearestSpawn = bestSpawn;

    targets.push_back(target);

    LOG_DEBUG("playerbots", "QuestObjectiveTargetsValue: Added item objective - quest {}, item {}, entry {}, distance {}",
        questId, itemId, bestEntry, bestDistance);
}

void QuestObjectiveTargetsValue::AddKillObjective(std::vector<QuestObjectiveTarget>& targets, uint32 questId,
    uint32 objectiveIndex, int32 reqNpcOrGo, uint32 needed, uint32 total)
{
    float distance;
    GuidPosition spawn = FindNearestSpawn(reqNpcOrGo, distance);

    if (!spawn)
    {
        LOG_DEBUG("playerbots", "QuestObjectiveTargetsValue: No spawn found for entry {} (quest {})",
            reqNpcOrGo, questId);
        return;
    }

    QuestObjectiveTarget target;
    target.questId = questId;
    target.objectiveIndex = objectiveIndex;
    target.entry = reqNpcOrGo;
    target.itemId = 0;  // Not an item objective
    target.needed = needed;
    target.total = total;
    target.distance = distance;
    target.nearestSpawn = spawn;

    targets.push_back(target);

    LOG_DEBUG("playerbots", "QuestObjectiveTargetsValue: Added kill/interact objective - quest {}, entry {}, distance {}",
        questId, reqNpcOrGo, distance);
}

GuidPosition QuestObjectiveTargetsValue::FindNearestSpawn(int32 entry, float& outDistance)
{
    outDistance = std::numeric_limits<float>::max();
    GuidPosition nearest;

    if (!bot)
        return nearest;

    uint32 botMapId = bot->GetMapId();
    float botX = bot->GetPositionX();
    float botY = bot->GetPositionY();
    float botZ = bot->GetPositionZ();

    if (entry > 0)  // Creature
    {
        // Search through all creature spawns
        for (auto const& pair : sObjectMgr->GetAllCreatureData())
        {
            CreatureData const& data = pair.second;
            if (data.id1 != (uint32)entry)
                continue;

            // Only consider spawns on the same map
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
    }
    else  // GameObject (negative entry)
    {
        uint32 goEntry = (uint32)(-entry);

        for (auto const& pair : sObjectMgr->GetAllGOData())
        {
            GameObjectData const& data = pair.second;
            if (data.id != goEntry)
                continue;

            // Only consider spawns on the same map
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
    }

    return nearest;
}

std::vector<int32> QuestObjectiveTargetsValue::FindItemDropSources(uint32 itemId)
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

            // Cast to access Entries (same pattern as LootValues.cpp)
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

QuestObjectiveTarget NearestQuestObjectiveValue::Calculate()
{
    std::vector<QuestObjectiveTarget> targets = AI_VALUE(std::vector<QuestObjectiveTarget>, "quest objective targets");

    if (targets.empty())
        return QuestObjectiveTarget();

    return targets.front();  // Already sorted by distance
}

bool HasQuestObjectiveNearbyValue::Calculate()
{
    std::vector<QuestObjectiveTarget> targets = AI_VALUE(std::vector<QuestObjectiveTarget>, "quest objective targets");

    if (targets.empty())
        return false;

    // Check if nearest target is within max distance
    return targets.front().distance <= maxDistance;
}
