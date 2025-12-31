/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#ifndef _PLAYERBOT_GANKSQUADTRIGGERS_H
#define _PLAYERBOT_GANKSQUADTRIGGERS_H

#include "Trigger.h"

class PlayerbotAI;

// Trigger when gank squad has a target nearby to attack
class GankSquadTargetNearTrigger : public Trigger
{
public:
    GankSquadTargetNearTrigger(PlayerbotAI* botAI);
    bool IsActive() override;
    std::string const getName() override { return "gank squad target near"; }
};

// Trigger when squad is in hunting state
class GankSquadHuntingTrigger : public Trigger
{
public:
    GankSquadHuntingTrigger(PlayerbotAI* botAI);
    bool IsActive() override;
    std::string const getName() override { return "gank squad hunting"; }
};

// Trigger when squad is patrolling
class GankSquadPatrolTrigger : public Trigger
{
public:
    GankSquadPatrolTrigger(PlayerbotAI* botAI);
    bool IsActive() override;
    std::string const getName() override { return "gank squad patrol"; }
};

// Trigger when squad members are spread out
class GankSquadSpreadTrigger : public Trigger
{
public:
    GankSquadSpreadTrigger(PlayerbotAI* botAI);
    bool IsActive() override;
    std::string const getName() override { return "gank squad spread"; }
};

#endif  // _PLAYERBOT_GANKSQUADTRIGGERS_H
