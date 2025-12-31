/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#ifndef _PLAYERBOT_GANKSQUADSTRATEGY_H
#define _PLAYERBOT_GANKSQUADSTRATEGY_H

#include "NonCombatStrategy.h"

class PlayerbotAI;

class GankSquadStrategy : public NonCombatStrategy
{
public:
    GankSquadStrategy(PlayerbotAI* botAI);

    std::string const getName() override { return "ganksquad"; }
    uint32 GetType() const override { return STRATEGY_TYPE_NONCOMBAT; }

    void InitTriggers(std::vector<TriggerNode*>& triggers) override;
    NextAction** getDefaultActions() override;
};

#endif  // _PLAYERBOT_GANKSQUADSTRATEGY_H
