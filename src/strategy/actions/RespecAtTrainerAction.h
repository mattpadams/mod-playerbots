/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_RESPECATTRAINERACTION_H
#define _PLAYERBOT_RESPECATTRAINERACTION_H

#include "Action.h"
#include "RoleStatWeights.h"

class PlayerbotAI;
class Creature;

// Action to respec talents at a class trainer
class RespecAtTrainerAction : public Action
{
public:
    RespecAtTrainerAction(PlayerbotAI* botAI) : Action(botAI, "respec at trainer") {}

    bool Execute(Event event) override;
    bool isPossible() override;
    bool isUseful() override;

private:
    // Find nearby class trainer
    Creature* FindClassTrainer() const;

    // Check if bot can afford respec
    bool CanAffordRespec(uint32 cost) const;

    // Perform the respec operation
    bool DoRespec(Creature* trainer, uint8 targetSpecTab);

    // Get respec cost in copper
    uint32 GetRespecCost() const;
};

// Action to evaluate if role switch is needed and queue it
class EvaluateRoleSwitchAction : public Action
{
public:
    EvaluateRoleSwitchAction(PlayerbotAI* botAI) : Action(botAI, "evaluate role switch") {}

    bool Execute(Event event) override;
    bool isUseful() override;

private:
    // Evaluate if the bot should switch roles based on group composition
    bool ShouldSwitchRole() const;
};

#endif
