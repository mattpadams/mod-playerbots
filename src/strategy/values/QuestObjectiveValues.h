/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_QUESTOBJECTIVEVALUES_H
#define _PLAYERBOT_QUESTOBJECTIVEVALUES_H

#include "NamedObjectContext.h"
#include "TravelMgr.h"
#include "Value.h"

class Player;
class PlayerbotAI;

// Data structure for a quest objective target
struct QuestObjectiveTarget
{
    uint32 questId;
    uint32 objectiveIndex;
    int32 entry;            // Positive = creature, negative = GO
    uint32 itemId;          // If collecting items (0 if not item objective)
    uint32 needed;          // How many more needed
    uint32 total;           // Total required
    float distance;         // Distance to nearest spawn
    GuidPosition nearestSpawn;

    bool IsCreature() const { return entry > 0; }
    bool IsGameObject() const { return entry < 0; }
    uint32 GetEntry() const { return entry > 0 ? entry : -entry; }
};

// Value: "quest objective targets" - Returns sorted list of quest objectives bot needs to complete
class QuestObjectiveTargetsValue : public CalculatedValue<std::vector<QuestObjectiveTarget>>
{
public:
    QuestObjectiveTargetsValue(PlayerbotAI* botAI)
        : CalculatedValue(botAI, "quest objective targets", 5) {}  // 5 second cache

    std::vector<QuestObjectiveTarget> Calculate() override;

private:
    void AddItemObjective(std::vector<QuestObjectiveTarget>& targets, uint32 questId, uint32 objectiveIndex,
                          uint32 itemId, uint32 needed, uint32 total);
    void AddKillObjective(std::vector<QuestObjectiveTarget>& targets, uint32 questId, uint32 objectiveIndex,
                          int32 reqNpcOrGo, uint32 needed, uint32 total);
    GuidPosition FindNearestSpawn(int32 entry, float& outDistance);
    std::vector<int32> FindItemDropSources(uint32 itemId);
};

// Value: "nearest quest objective" - Returns the single nearest quest objective
class NearestQuestObjectiveValue : public CalculatedValue<QuestObjectiveTarget>
{
public:
    NearestQuestObjectiveValue(PlayerbotAI* botAI)
        : CalculatedValue(botAI, "nearest quest objective", 2) {}

    QuestObjectiveTarget Calculate() override;
};

// Value: "has quest objective nearby" - Returns true if there's a reachable quest objective
class HasQuestObjectiveNearbyValue : public BoolCalculatedValue
{
public:
    HasQuestObjectiveNearbyValue(PlayerbotAI* botAI, float maxDistance = 500.0f)
        : BoolCalculatedValue(botAI, "has quest objective nearby", 2), maxDistance(maxDistance) {}

    bool Calculate() override;

private:
    float maxDistance;
};

#endif
