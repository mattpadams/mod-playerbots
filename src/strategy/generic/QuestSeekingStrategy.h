/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_QUESTSEEKINGSTRATEGY_H
#define _PLAYERBOT_QUESTSEEKINGSTRATEGY_H

#include "Strategy.h"

class PlayerbotAI;

class QuestSeekingStrategy : public Strategy
{
public:
    QuestSeekingStrategy(PlayerbotAI* botAI) : Strategy(botAI) {}

    void InitTriggers(std::vector<TriggerNode*>& triggers) override;
    std::string const getName() override { return "quest seek"; }
};

#endif
