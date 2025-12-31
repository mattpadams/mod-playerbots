/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_QUESTPRIORITYVALUES_H
#define _PLAYERBOT_QUESTPRIORITYVALUES_H

#include "NamedObjectContext.h"
#include "QuestValues.h"
#include "Value.h"

class Player;
class PlayerbotAI;

// Quest score factors enumeration
enum QuestScoreFactor : uint32
{
    QUEST_SCORE_XP_EFFICIENCY    = 0,  // XP per estimated time
    QUEST_SCORE_ZONE_FLOW        = 1,  // Alignment with zone progression
    QUEST_SCORE_PROXIMITY        = 2,  // Distance to objectives
    QUEST_SCORE_REWARD_VALUE     = 3,  // Role-appropriate gear score
    QUEST_SCORE_CLASS_QUEST      = 4,  // Class-specific quest bonus
    QUEST_SCORE_CHAIN_PROGRESS   = 5,  // Quest chain advancement
    QUEST_SCORE_FACTOR_MAX       = 6
};

// Quest type classification
enum QuestTypeClass : uint8
{
    QUEST_TYPE_CLASS_NORMAL       = 0,
    QUEST_TYPE_CLASS_CLASS_QUEST  = 1,
    QUEST_TYPE_CLASS_CHAIN_QUEST  = 2,
    QUEST_TYPE_CLASS_DUNGEON      = 3,
    QUEST_TYPE_CLASS_ELITE        = 4,
    QUEST_TYPE_CLASS_ESCORT       = 5
};

// Quest priority data structure
struct QuestPriorityData
{
    uint32 questId;
    float totalScore;
    float factorScores[QUEST_SCORE_FACTOR_MAX];
    QuestTypeClass typeClass;
    uint32 estimatedTimeMinutes;
    float distanceToObjective;
    bool hasRoleReward;
    bool isDungeonQuest;

    QuestPriorityData() : questId(0), totalScore(0.0f), typeClass(QUEST_TYPE_CLASS_NORMAL),
        estimatedTimeMinutes(15), distanceToObjective(0.0f), hasRoleReward(false), isDungeonQuest(false)
    {
        for (uint32 i = 0; i < QUEST_SCORE_FACTOR_MAX; ++i)
            factorScores[i] = 0.0f;
    }

    bool operator<(const QuestPriorityData& other) const {
        return totalScore > other.totalScore; // Higher score = higher priority
    }
};

// Prioritized quest list value - returns sorted list of quests by score
class PrioritizedQuestsValue : public CalculatedValue<std::vector<QuestPriorityData>>
{
public:
    PrioritizedQuestsValue(PlayerbotAI* botAI)
        : CalculatedValue(botAI, "prioritized quests", 30) {} // Cache for 30 seconds

    std::vector<QuestPriorityData> Calculate() override;

private:
    QuestPriorityData CalculateQuestPriority(uint32 questId);
    float CalculateXPEfficiency(Quest const* quest);
    float CalculateZoneFlowScore(Quest const* quest);
    float CalculateProximityScore(Quest const* quest);
    float CalculateRewardScore(Quest const* quest);
    float CalculateClassQuestBonus(Quest const* quest);
    float CalculateChainProgressScore(Quest const* quest);
    QuestTypeClass ClassifyQuest(Quest const* quest);
    uint32 EstimateCompletionTime(Quest const* quest);
    bool IsEquipmentUpgrade(ItemTemplate const* proto);
    float GetDistanceToNearestObjective(uint32 questId);
};

// Best quest to pursue value (single quest selection)
class BestQuestValue : public Uint32CalculatedValue
{
public:
    BestQuestValue(PlayerbotAI* botAI)
        : Uint32CalculatedValue(botAI, "best quest", 10) {} // Cache for 10 seconds

    uint32 Calculate() override;  // Returns questId or 0
};

// Best available quest to accept
class BestAvailableQuestValue : public Uint32CalculatedValue
{
public:
    BestAvailableQuestValue(PlayerbotAI* botAI)
        : Uint32CalculatedValue(botAI, "best available quest", 10) {}

    uint32 Calculate() override;
};

// Quest reward upgrade check for specific role
class QuestHasRoleUpgradeValue : public BoolCalculatedValue, public Qualified
{
public:
    QuestHasRoleUpgradeValue(PlayerbotAI* botAI)
        : BoolCalculatedValue(botAI, "quest has role upgrade", 5) {}

    bool Calculate() override;
};

// Zone quest completion percentage
class ZoneQuestProgressValue : public CalculatedValue<float>, public Qualified
{
public:
    ZoneQuestProgressValue(PlayerbotAI* botAI)
        : CalculatedValue(botAI, "zone quest progress", 60) {} // Cache for 60 seconds

    float Calculate() override;  // Returns 0.0-1.0
};

// Number of quests bot has in current zone
class ZoneQuestCountValue : public Uint32CalculatedValue, public Qualified
{
public:
    ZoneQuestCountValue(PlayerbotAI* botAI)
        : Uint32CalculatedValue(botAI, "zone quest count", 30) {}

    uint32 Calculate() override;
};

// Check if bot should stay in current zone or move on
class ShouldChangeZoneValue : public BoolCalculatedValue
{
public:
    ShouldChangeZoneValue(PlayerbotAI* botAI)
        : BoolCalculatedValue(botAI, "should change zone", 60) {}

    bool Calculate() override;
};

#endif
