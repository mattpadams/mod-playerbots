/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_CONTAINERQUESTOBJECTIVEVALUE_H
#define _PLAYERBOT_CONTAINERQUESTOBJECTIVEVALUE_H

#include "NamedObjectContext.h"
#include "TravelMgr.h"
#include "Value.h"

class Player;
class PlayerbotAI;

// Data structure for a container-only quest objective
struct ContainerQuestObjective
{
    uint32 questId;
    uint32 objectiveIndex;
    uint32 containerEntry;      // GameObject entry (always positive)
    uint32 itemId;
    uint32 needed;
    uint32 total;
    float distance;
    GuidPosition nearestSpawn;
    ObjectGuid nearestContainerGuid;  // GUID of spawned container if found
    bool isContainerOnly;             // True if item ONLY comes from containers
};

// Value: "container quest objectives" - Returns container-only quest objectives within range
class ContainerQuestObjectivesValue : public CalculatedValue<std::vector<ContainerQuestObjective>>
{
public:
    ContainerQuestObjectivesValue(PlayerbotAI* botAI, float maxDistance = 30.0f)
        : CalculatedValue(botAI, "container quest objectives", 3),
          maxDistance(maxDistance) {}

    std::vector<ContainerQuestObjective> Calculate() override;

private:
    bool IsContainerOnlyItem(uint32 itemId, std::vector<int32>& outSources);
    std::vector<int32> FindItemDropSources(uint32 itemId);
    ObjectGuid FindNearestSpawnedContainer(uint32 goEntry, float maxRange, float& outDistance);
    GuidPosition FindNearestContainerSpawn(uint32 goEntry, float& outDistance);

    float maxDistance;
};

// Value: "container loot blocked" - True if enemies are near the target container
class ContainerLootBlockedValue : public BoolCalculatedValue
{
public:
    ContainerLootBlockedValue(PlayerbotAI* botAI, float enemyRadius = 40.0f)
        : BoolCalculatedValue(botAI, "container loot blocked", 2),
          enemyRadius(enemyRadius) {}

    bool Calculate() override;

private:
    float enemyRadius;
};

// Value: "enemies near quest container" - Returns list of enemies near the nearest container objective
class EnemiesNearQuestContainerValue : public CalculatedValue<GuidVector>
{
public:
    EnemiesNearQuestContainerValue(PlayerbotAI* botAI, float enemyRadius = 40.0f)
        : CalculatedValue(botAI, "enemies near quest container", 2),
          enemyRadius(enemyRadius) {}

    GuidVector Calculate() override;

private:
    float enemyRadius;
};

#endif
