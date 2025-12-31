/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#include "GankSquadStrategy.h"
#include "GankSquadActions.h"
#include "GankSquadTriggers.h"

GankSquadStrategy::GankSquadStrategy(PlayerbotAI* botAI) : NonCombatStrategy(botAI)
{
}

void GankSquadStrategy::InitTriggers(std::vector<TriggerNode*>& triggers)
{
    // High priority: attack target when spotted
    triggers.push_back(new TriggerNode(
        "gank squad target near",
        NextAction::array(0, new NextAction("attack gank target", 80.0f), nullptr)));

    // Medium priority: hunt target if squad is hunting
    triggers.push_back(new TriggerNode(
        "gank squad hunting",
        NextAction::array(0, new NextAction("hunt gank target", 60.0f), nullptr)));

    // Medium priority: regroup if spread out
    triggers.push_back(new TriggerNode(
        "gank squad spread",
        NextAction::array(0, new NextAction("regroup squad", 55.0f), nullptr)));

    // Low priority: patrol when idle
    triggers.push_back(new TriggerNode(
        "gank squad patrol",
        NextAction::array(0, new NextAction("patrol gank zone", 20.0f), nullptr)));
}

NextAction** GankSquadStrategy::getDefaultActions()
{
    return NextAction::array(0, new NextAction("patrol gank zone", 1.0f), nullptr);
}
