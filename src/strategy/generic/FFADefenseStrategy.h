/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_FFADEFENSESTRATEGY_H
#define _PLAYERBOT_FFADEFENSESTRATEGY_H

#include "Strategy.h"

class PlayerbotAI;

// Strategy for FFA PvP defense behavior
class FFADefenseStrategy : public Strategy
{
public:
    FFADefenseStrategy(PlayerbotAI* botAI);

    std::string const getName() override { return "ffa"; }
    uint32 GetType() const override { return STRATEGY_TYPE_COMBAT; }

protected:
    void InitTriggers(std::vector<TriggerNode*>& triggers) override;
};

#endif
