/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "FFADefenseStrategy.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"

FFADefenseStrategy::FFADefenseStrategy(PlayerbotAI* botAI) : Strategy(botAI)
{
}

void FFADefenseStrategy::InitTriggers(std::vector<TriggerNode*>& triggers)
{
    // Defensive mode - only attack if attacked first
    triggers.push_back(new TriggerNode(
        "ffa under attack",
        NextAction::array(0, new NextAction("attack ffa enemy", ACTION_HIGH + 2), nullptr)));

    // Territorial mode - attack enemies in our territory
    triggers.push_back(new TriggerNode(
        "ffa territorial",
        NextAction::array(0, new NextAction("attack ffa enemy", ACTION_HIGH + 1), nullptr)));

    // Aggressive mode - hunt enemies in range
    triggers.push_back(new TriggerNode(
        "ffa aggressive",
        NextAction::array(0, new NextAction("attack ffa enemy", ACTION_HIGH), nullptr)));

    // When outnumbered, consider fleeing (lower priority)
    triggers.push_back(new TriggerNode(
        "ffa outnumbered",
        NextAction::array(0, new NextAction("flee", ACTION_NORMAL), nullptr)));
}
