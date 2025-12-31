/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#ifndef _PLAYERBOT_GANKSQUADACTIONS_H
#define _PLAYERBOT_GANKSQUADACTIONS_H

#include "MovementActions.h"
#include "AttackAction.h"

class PlayerbotAI;

// Attack the gank squad's target
class AttackGankTargetAction : public AttackAction
{
public:
    AttackGankTargetAction(PlayerbotAI* botAI);
    bool Execute(Event event) override;
    bool isUseful() override;
    std::string const getName() override { return "attack gank target"; }
};

// Move toward gank squad's target
class HuntGankTargetAction : public MovementAction
{
public:
    HuntGankTargetAction(PlayerbotAI* botAI);
    bool Execute(Event event) override;
    bool isUseful() override;
    std::string const getName() override { return "hunt gank target"; }
};

// Patrol the gank zone
class PatrolGankZoneAction : public MovementAction
{
public:
    PatrolGankZoneAction(PlayerbotAI* botAI);
    bool Execute(Event event) override;
    bool isUseful() override;
    std::string const getName() override { return "patrol gank zone"; }
};

// Regroup with squad leader
class RegroupSquadAction : public MovementAction
{
public:
    RegroupSquadAction(PlayerbotAI* botAI);
    bool Execute(Event event) override;
    bool isUseful() override;
    std::string const getName() override { return "regroup squad"; }
};

#endif  // _PLAYERBOT_GANKSQUADACTIONS_H
