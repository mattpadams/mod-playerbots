/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_QUESTOBJECTIVETRIGGERS_H
#define _PLAYERBOT_QUESTOBJECTIVETRIGGERS_H

#include "Trigger.h"
#include "QuestObjectiveValues.h"
#include "ContainerQuestObjectiveValue.h"

class PlayerbotAI;

class HasIncompleteQuestObjectiveTrigger : public Trigger
{
public:
    HasIncompleteQuestObjectiveTrigger(PlayerbotAI* botAI, float maxDistance = 500.0f)
        : Trigger(botAI, "has incomplete quest objective", 5), maxDistance(maxDistance) {}

    bool IsActive() override;

private:
    float maxDistance;
};

// Trigger for container-only quest objectives within range
class ContainerQuestObjectiveNearbyTrigger : public Trigger
{
public:
    ContainerQuestObjectiveNearbyTrigger(PlayerbotAI* botAI, float maxDistance = 30.0f)
        : Trigger(botAI, "container quest objective nearby", 3), maxDistance(maxDistance) {}

    bool IsActive() override;

private:
    float maxDistance;
};

#endif
