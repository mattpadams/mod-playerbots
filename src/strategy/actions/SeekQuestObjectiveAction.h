/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_SEEKQUESTOBJECTIVEACTION_H
#define _PLAYERBOT_SEEKQUESTOBJECTIVEACTION_H

#include "MovementActions.h"
#include "QuestObjectiveValues.h"

class PlayerbotAI;

class SeekQuestObjectiveAction : public MovementAction
{
public:
    SeekQuestObjectiveAction(PlayerbotAI* botAI)
        : MovementAction(botAI, "seek quest objective"), maxSeekDistance(500.0f) {}

    bool Execute(Event event) override;
    bool isUseful() override;

private:
    bool SeekTarget(QuestObjectiveTarget& target);
    float maxSeekDistance;
};

#endif
