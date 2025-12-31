/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "QuestPriorityValues.h"

#include "MapMgr.h"
#include "Playerbots.h"
#include "PlayerbotAIConfig.h"
#include "QuestZoneData.h"
#include "SharedValueContext.h"

std::vector<QuestPriorityData> PrioritizedQuestsValue::Calculate()
{
    std::vector<QuestPriorityData> result;

    // Get all quests the bot currently has
    QuestStatusMap& questStatusMap = bot->getQuestStatusMap();

    for (auto& questStatus : questStatusMap)
    {
        uint32 questId = questStatus.first;

        // Only prioritize incomplete quests
        if (questStatus.second.Status != QUEST_STATUS_INCOMPLETE)
            continue;

        Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
        if (!quest)
            continue;

        QuestPriorityData priorityData = CalculateQuestPriority(questId);
        if (priorityData.totalScore > 0.0f)
            result.push_back(priorityData);
    }

    // Sort by total score (higher = better)
    std::sort(result.begin(), result.end());

    return result;
}

QuestPriorityData PrioritizedQuestsValue::CalculateQuestPriority(uint32 questId)
{
    QuestPriorityData data;
    data.questId = questId;

    Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
    if (!quest)
        return data;

    // Classify quest type
    data.typeClass = ClassifyQuest(quest);
    data.isDungeonQuest = (data.typeClass == QUEST_TYPE_CLASS_DUNGEON);
    data.estimatedTimeMinutes = EstimateCompletionTime(quest);
    data.distanceToObjective = GetDistanceToNearestObjective(questId);

    // Calculate individual factor scores
    data.factorScores[QUEST_SCORE_XP_EFFICIENCY] = CalculateXPEfficiency(quest);
    data.factorScores[QUEST_SCORE_ZONE_FLOW] = CalculateZoneFlowScore(quest);
    data.factorScores[QUEST_SCORE_PROXIMITY] = CalculateProximityScore(quest);
    data.factorScores[QUEST_SCORE_REWARD_VALUE] = CalculateRewardScore(quest);
    data.factorScores[QUEST_SCORE_CLASS_QUEST] = CalculateClassQuestBonus(quest);
    data.factorScores[QUEST_SCORE_CHAIN_PROGRESS] = CalculateChainProgressScore(quest);

    // Get weights from config
    float weights[QUEST_SCORE_FACTOR_MAX] = {
        sPlayerbotAIConfig->questPriorityXPEfficiency,
        sPlayerbotAIConfig->questPriorityZoneFlow,
        sPlayerbotAIConfig->questPriorityProximity,
        sPlayerbotAIConfig->questPriorityRewardValue,
        sPlayerbotAIConfig->questPriorityClassQuest,
        sPlayerbotAIConfig->questPriorityChainProgress
    };

    // Calculate total weighted score
    data.totalScore = 0.0f;
    for (uint32 i = 0; i < QUEST_SCORE_FACTOR_MAX; ++i)
        data.totalScore += data.factorScores[i] * weights[i];

    // Penalize dungeon quests when solo
    if (data.isDungeonQuest && !bot->GetGroup())
        data.totalScore *= 0.3f;

    // Penalize elite quests when solo
    if (data.typeClass == QUEST_TYPE_CLASS_ELITE && !bot->GetGroup())
        data.totalScore *= 0.5f;

    return data;
}

float PrioritizedQuestsValue::CalculateXPEfficiency(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    uint32 xpReward = bot->CalculateQuestRewardXP(quest);
    uint32 estimatedMinutes = EstimateCompletionTime(quest);

    if (estimatedMinutes == 0)
        estimatedMinutes = 15; // Default

    // XP per minute, normalized to baseline
    float xpPerMinute = (float)xpReward / estimatedMinutes;
    float baselineXpPerMinute = bot->GetLevel() * 5.0f; // Expected baseline

    // Normalize to 0-1 range, cap at 2x baseline
    return std::min(1.0f, xpPerMinute / (baselineXpPerMinute * 2.0f));
}

float PrioritizedQuestsValue::CalculateZoneFlowScore(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    int32 questZoneOrSort = quest->GetZoneOrSort();
    uint32 botZone = bot->GetZoneId();

    // Same zone gets high score
    if (questZoneOrSort > 0 && (uint32)questZoneOrSort == botZone)
        return 1.0f;

    // Use zone data for adjacent zones
    if (questZoneOrSort > 0)
    {
        float zoneFlowScore = sQuestZoneData->GetZoneFlowScore(botZone, questZoneOrSort, bot->GetLevel());
        if (zoneFlowScore > 0.0f)
            return zoneFlowScore;
    }

    // Different zone with no flow connection
    return 0.3f;
}

float PrioritizedQuestsValue::CalculateProximityScore(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    float distance = GetDistanceToNearestObjective(quest->GetQuestId());

    // Normalize distance: closer = higher score
    // 0 distance = 1.0, 1000+ yards = 0.0
    if (distance <= 0.0f)
        return 1.0f;

    if (distance > 1000.0f)
        return 0.0f;

    return 1.0f - (distance / 1000.0f);
}

float PrioritizedQuestsValue::CalculateRewardScore(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    float bestScore = 0.0f;
    bool hasUpgrade = false;

    // Check choice rewards
    for (uint8 i = 0; i < QUEST_REWARD_CHOICES_COUNT; ++i)
    {
        uint32 itemId = quest->RewardChoiceItemId[i];
        if (!itemId)
            continue;

        ItemTemplate const* proto = sObjectMgr->GetItemTemplate(itemId);
        if (!proto)
            continue;

        // Check if it's equipment
        if (proto->Class == ITEM_CLASS_ARMOR || proto->Class == ITEM_CLASS_WEAPON)
        {
            if (IsEquipmentUpgrade(proto))
            {
                hasUpgrade = true;
                bestScore = std::max(bestScore, 0.8f);
            }
            else
            {
                bestScore = std::max(bestScore, 0.3f);
            }
        }
    }

    // Check fixed rewards
    for (uint8 i = 0; i < QUEST_REWARDS_COUNT; ++i)
    {
        uint32 itemId = quest->RewardItemId[i];
        if (!itemId)
            continue;

        ItemTemplate const* proto = sObjectMgr->GetItemTemplate(itemId);
        if (!proto)
            continue;

        if (proto->Class == ITEM_CLASS_ARMOR || proto->Class == ITEM_CLASS_WEAPON)
        {
            if (IsEquipmentUpgrade(proto))
            {
                hasUpgrade = true;
                bestScore = std::max(bestScore, 0.8f);
            }
            else
            {
                bestScore = std::max(bestScore, 0.3f);
            }
        }
    }

    // Gold reward consideration
    int32 gold = quest->GetRewOrReqMoney(bot->GetLevel());
    if (gold > 0)
    {
        float goldScore = std::min(0.3f, (float)gold / (bot->GetLevel() * 1000.0f));
        bestScore = std::max(bestScore, goldScore);
    }

    return std::min(1.0f, hasUpgrade ? bestScore * 1.5f : bestScore);
}

float PrioritizedQuestsValue::CalculateClassQuestBonus(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    // Check if this is a class-specific quest
    if (quest->GetRequiredClasses() & bot->getClassMask())
        return 1.0f; // Maximum bonus for class quests

    return 0.0f;
}

float PrioritizedQuestsValue::CalculateChainProgressScore(Quest const* quest)
{
    if (!quest)
        return 0.0f;

    // Check if this quest unlocks other quests
    uint32 nextQuestId = quest->GetNextQuestId();
    bool hasFollowUp = (nextQuestId != 0);

    // Check if quest is part of a chain we're progressing
    bool hasPrereq = false;
    if (quest->GetPrevQuestId() != 0)
        hasPrereq = true;

    if (hasFollowUp && hasPrereq)
        return 0.8f; // Mid-chain quest
    else if (hasFollowUp)
        return 0.6f; // Chain starter
    else if (hasPrereq)
        return 0.9f; // Chain finisher (high priority to complete)

    return 0.0f; // Standalone quest
}

QuestTypeClass PrioritizedQuestsValue::ClassifyQuest(Quest const* quest)
{
    if (!quest)
        return QUEST_TYPE_CLASS_NORMAL;

    // Check quest flags and type
    if (quest->GetType() == QUEST_TYPE_DUNGEON)
        return QUEST_TYPE_CLASS_DUNGEON;

    if (quest->GetFlags() & QUEST_FLAGS_RAID)
        return QUEST_TYPE_CLASS_DUNGEON; // Treat raid quests similarly

    // Check for elite quests (suggested players > 1)
    if (quest->GetSuggestedPlayers() > 1)
        return QUEST_TYPE_CLASS_ELITE;

    // Class-specific quests
    if (quest->GetRequiredClasses())
        return QUEST_TYPE_CLASS_CLASS_QUEST;

    // Chain quests
    if (quest->GetPrevQuestId() != 0 || quest->GetNextQuestId() != 0)
        return QUEST_TYPE_CLASS_CHAIN_QUEST;

    // Timed quests (often escort-like)
    if (quest->HasSpecialFlag(QUEST_SPECIAL_FLAGS_TIMED))
        return QUEST_TYPE_CLASS_ESCORT;

    return QUEST_TYPE_CLASS_NORMAL;
}

uint32 PrioritizedQuestsValue::EstimateCompletionTime(Quest const* quest)
{
    if (!quest)
        return 15;

    uint32 baseTime = 10; // Base minutes

    // Add time for each objective
    for (uint32 i = 0; i < QUEST_OBJECTIVES_COUNT; i++)
    {
        // Kill/interact objectives
        if (quest->RequiredNpcOrGoCount[i] > 0)
        {
            baseTime += quest->RequiredNpcOrGoCount[i] * 2; // 2 min per kill/interact
        }

        // Item collection objectives
        if (quest->RequiredItemCount[i] > 0)
        {
            baseTime += quest->RequiredItemCount[i] * 3; // 3 min per item
        }
    }

    // Modifier for quest type
    QuestTypeClass typeClass = ClassifyQuest(quest);
    switch (typeClass)
    {
        case QUEST_TYPE_CLASS_ELITE:
            baseTime = (uint32)(baseTime * 1.5f);
            break;
        case QUEST_TYPE_CLASS_DUNGEON:
            baseTime = (uint32)(baseTime * 3.0f);
            break;
        case QUEST_TYPE_CLASS_ESCORT:
            baseTime = (uint32)(baseTime * 1.3f);
            break;
        default:
            break;
    }

    return baseTime;
}

bool PrioritizedQuestsValue::IsEquipmentUpgrade(ItemTemplate const* proto)
{
    if (!proto)
        return false;

    // Check if bot can use the item
    if (proto->RequiredLevel > bot->GetLevel())
        return false;

    // Get current item in slot
    uint8 slot = EQUIPMENT_SLOT_END;
    switch (proto->InventoryType)
    {
        case INVTYPE_HEAD:      slot = EQUIPMENT_SLOT_HEAD; break;
        case INVTYPE_NECK:      slot = EQUIPMENT_SLOT_NECK; break;
        case INVTYPE_SHOULDERS: slot = EQUIPMENT_SLOT_SHOULDERS; break;
        case INVTYPE_CHEST:
        case INVTYPE_ROBE:      slot = EQUIPMENT_SLOT_CHEST; break;
        case INVTYPE_WAIST:     slot = EQUIPMENT_SLOT_WAIST; break;
        case INVTYPE_LEGS:      slot = EQUIPMENT_SLOT_LEGS; break;
        case INVTYPE_FEET:      slot = EQUIPMENT_SLOT_FEET; break;
        case INVTYPE_WRISTS:    slot = EQUIPMENT_SLOT_WRISTS; break;
        case INVTYPE_HANDS:     slot = EQUIPMENT_SLOT_HANDS; break;
        case INVTYPE_FINGER:    slot = EQUIPMENT_SLOT_FINGER1; break;
        case INVTYPE_TRINKET:   slot = EQUIPMENT_SLOT_TRINKET1; break;
        case INVTYPE_CLOAK:     slot = EQUIPMENT_SLOT_BACK; break;
        case INVTYPE_WEAPON:
        case INVTYPE_WEAPONMAINHAND:
        case INVTYPE_2HWEAPON:  slot = EQUIPMENT_SLOT_MAINHAND; break;
        case INVTYPE_SHIELD:
        case INVTYPE_WEAPONOFFHAND:
        case INVTYPE_HOLDABLE:  slot = EQUIPMENT_SLOT_OFFHAND; break;
        case INVTYPE_RANGED:
        case INVTYPE_THROWN:
        case INVTYPE_RANGEDRIGHT: slot = EQUIPMENT_SLOT_RANGED; break;
        default: return false;
    }

    if (slot == EQUIPMENT_SLOT_END)
        return false;

    Item* currentItem = bot->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
    if (!currentItem)
        return true; // Empty slot = upgrade

    // Compare item levels as simple heuristic
    return proto->ItemLevel > currentItem->GetTemplate()->ItemLevel;
}

float PrioritizedQuestsValue::GetDistanceToNearestObjective(uint32 questId)
{
    std::vector<GuidPosition> objectives = AI_VALUE(std::vector<GuidPosition>, "active quest objectives");

    float minDistance = 10000.0f;
    bool found = false;

    for (const auto& guidp : objectives)
    {
        // The objectives value returns all objectives, we need to filter by quest
        // For now, return distance to nearest objective of any incomplete quest
        float dist = bot->GetDistance(guidp.GetWorldLocation());
        if (dist < minDistance)
        {
            minDistance = dist;
            found = true;
        }
    }

    return found ? minDistance : 10000.0f;
}

// Best Quest Value - returns single best quest to work on
uint32 BestQuestValue::Calculate()
{
    std::vector<QuestPriorityData> prioritized = AI_VALUE(std::vector<QuestPriorityData>, "prioritized quests");

    if (prioritized.empty())
        return 0;

    // Return the highest scoring quest
    return prioritized[0].questId;
}

// Best Available Quest Value - returns best quest to accept
uint32 BestAvailableQuestValue::Calculate()
{
    questGiverMap qGivers = GAI_VALUE2(questGiverMap, "quest givers", bot->GetLevel());

    float bestScore = 0.0f;
    uint32 bestQuestId = 0;

    for (auto& qGiver : qGivers)
    {
        uint32 questId = qGiver.first;
        Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
        if (!quest)
            continue;

        if (!bot->CanTakeQuest(quest, false))
            continue;

        QuestStatus status = bot->GetQuestStatus(questId);
        if (status != QUEST_STATUS_NONE)
            continue;

        // Simple scoring for available quests
        float score = 0.0f;

        // XP value
        uint32 xp = bot->CalculateQuestRewardXP(quest);
        score += (float)xp / (bot->GetLevel() * 100.0f);

        // Class quest bonus
        if (quest->GetRequiredClasses() & bot->getClassMask())
            score += 1.0f;

        // Chain quest bonus
        if (quest->GetNextQuestId() != 0)
            score += 0.3f;

        // Zone match bonus
        int32 questZone = quest->GetZoneOrSort();
        if (questZone > 0 && (uint32)questZone == bot->GetZoneId())
            score += 0.5f;

        if (score > bestScore)
        {
            bestScore = score;
            bestQuestId = questId;
        }
    }

    return bestQuestId;
}

// Quest Has Role Upgrade Value
bool QuestHasRoleUpgradeValue::Calculate()
{
    uint32 questId = stoi(getQualifier());
    Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
    if (!quest)
        return false;

    // Check choice rewards for role-appropriate items
    for (uint8 i = 0; i < QUEST_REWARD_CHOICES_COUNT; ++i)
    {
        uint32 itemId = quest->RewardChoiceItemId[i];
        if (!itemId)
            continue;

        ItemTemplate const* proto = sObjectMgr->GetItemTemplate(itemId);
        if (!proto)
            continue;

        if (proto->Class == ITEM_CLASS_ARMOR || proto->Class == ITEM_CLASS_WEAPON)
        {
            // Could add role-specific stat checking here
            if (proto->RequiredLevel <= bot->GetLevel())
                return true;
        }
    }

    return false;
}

// Zone Quest Progress Value
float ZoneQuestProgressValue::Calculate()
{
    uint32 zoneId = 0;
    std::string const q = getQualifier();
    if (!q.empty())
        zoneId = stoi(q);
    else
        zoneId = bot->GetZoneId();

    // Count total quests in zone and completed quests
    questGiverMap qGivers = GAI_VALUE2(questGiverMap, "quest givers", bot->GetLevel());

    uint32 totalQuests = 0;
    uint32 completedQuests = 0;

    for (auto& qGiver : qGivers)
    {
        uint32 questId = qGiver.first;
        Quest const* quest = sObjectMgr->GetQuestTemplate(questId);
        if (!quest)
            continue;

        int32 questZone = quest->GetZoneOrSort();
        if (questZone <= 0 || (uint32)questZone != zoneId)
            continue;

        totalQuests++;

        QuestStatus status = bot->GetQuestStatus(questId);
        if (status == QUEST_STATUS_REWARDED)
            completedQuests++;
    }

    if (totalQuests == 0)
        return 1.0f; // No quests = zone complete

    return (float)completedQuests / (float)totalQuests;
}

// Zone Quest Count Value
uint32 ZoneQuestCountValue::Calculate()
{
    uint32 zoneId = 0;
    std::string const q = getQualifier();
    if (!q.empty())
        zoneId = stoi(q);
    else
        zoneId = bot->GetZoneId();

    uint32 count = 0;
    QuestStatusMap& questStatusMap = bot->getQuestStatusMap();

    for (auto& questStatus : questStatusMap)
    {
        if (questStatus.second.Status != QUEST_STATUS_INCOMPLETE)
            continue;

        Quest const* quest = sObjectMgr->GetQuestTemplate(questStatus.first);
        if (!quest)
            continue;

        int32 questZone = quest->GetZoneOrSort();
        if (questZone > 0 && (uint32)questZone == zoneId)
            count++;
    }

    return count;
}

// Should Change Zone Value
bool ShouldChangeZoneValue::Calculate()
{
    uint32 zoneId = bot->GetZoneId();
    float progress = AI_VALUE2(float, "zone quest progress", std::to_string(zoneId));
    uint32 questCount = AI_VALUE2(uint32, "zone quest count", std::to_string(zoneId));

    // Change zone if progress is high and few quests remain
    if (progress > 0.8f && questCount < 3)
        return true;

    // Check if zone is appropriate for level
    const ZoneProgressionInfo* zoneInfo = sQuestZoneData->GetZoneInfo(zoneId);
    if (zoneInfo)
    {
        // Zone is too low level
        if (bot->GetLevel() > zoneInfo->maxLevel + 3)
            return true;
    }

    return false;
}
