/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_FFAPVPTRIGGERS_H
#define _PLAYERBOT_FFAPVPTRIGGERS_H

#include "Trigger.h"

class PlayerbotAI;

// Trigger when FFA enemy player is nearby
class FFAEnemyNearbyTrigger : public Trigger
{
public:
    FFAEnemyNearbyTrigger(PlayerbotAI* botAI) : Trigger(botAI, "ffa enemy nearby", 2) {}

    bool IsActive() override;
};

// Trigger when being attacked by FFA enemy
class FFAUnderAttackTrigger : public Trigger
{
public:
    FFAUnderAttackTrigger(PlayerbotAI* botAI) : Trigger(botAI, "ffa under attack", 1) {}

    bool IsActive() override;
};

// Trigger for territorial mode - enemy entered our territory
class FFATerritorialTrigger : public Trigger
{
public:
    FFATerritorialTrigger(PlayerbotAI* botAI) : Trigger(botAI, "ffa territorial", 2) {}

    bool IsActive() override;
};

// Trigger for aggressive mode - enemy in hunt range
class FFAAggressiveTrigger : public Trigger
{
public:
    FFAAggressiveTrigger(PlayerbotAI* botAI) : Trigger(botAI, "ffa aggressive", 3) {}

    bool IsActive() override;
};

// Trigger when multiple FFA enemies are nearby (might want to flee)
class FFAOutnumberedTrigger : public Trigger
{
public:
    FFAOutnumberedTrigger(PlayerbotAI* botAI) : Trigger(botAI, "ffa outnumbered", 2) {}

    bool IsActive() override;
};

#endif
