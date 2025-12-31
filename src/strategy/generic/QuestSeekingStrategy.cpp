/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "QuestSeekingStrategy.h"

#include "Playerbots.h"

void QuestSeekingStrategy::InitTriggers(std::vector<TriggerNode*>& triggers)
{
    // When bot has an incomplete quest objective nearby, seek it out
    // Priority is relatively low (4.0f) to not interfere with combat or higher priority actions
    triggers.push_back(new TriggerNode(
        "has incomplete quest objective",
        NextAction::array(0, new NextAction("seek quest objective", 4.0f), nullptr)));

    // Container-specific quest objective handling
    // Higher priority (5.0f) than general seek to ensure proper enemy safety checks
    triggers.push_back(new TriggerNode(
        "container quest objective nearby",
        NextAction::array(0, new NextAction("loot quest container", 5.0f), nullptr)));
}
