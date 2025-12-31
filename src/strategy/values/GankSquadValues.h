/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#ifndef _PLAYERBOT_GANKSQUADVALUES_H
#define _PLAYERBOT_GANKSQUADVALUES_H

#include "Value.h"
#include "GankSquadMgr.h"

class PlayerbotAI;

// Returns the gank squad's current target
class GankSquadTargetValue : public UnitCalculatedValue
{
public:
    GankSquadTargetValue(PlayerbotAI* botAI);
    Unit* Calculate() override;
    std::string const getName() override { return "gank squad target"; }
};

// Returns the gank squad's state as uint8
class GankSquadStateValue : public CalculatedValue<uint8>
{
public:
    GankSquadStateValue(PlayerbotAI* botAI);
    uint8 Calculate() override;
    std::string const getName() override { return "gank squad state"; }
};

// Returns the gank squad's leader
class GankSquadLeaderValue : public UnitCalculatedValue
{
public:
    GankSquadLeaderValue(PlayerbotAI* botAI);
    Unit* Calculate() override;
    std::string const getName() override { return "gank squad leader"; }
};

// Returns whether bot is in a gank squad
class InGankSquadValue : public BoolCalculatedValue
{
public:
    InGankSquadValue(PlayerbotAI* botAI);
    bool Calculate() override;
    std::string const getName() override { return "in gank squad"; }
};

#endif  // _PLAYERBOT_GANKSQUADVALUES_H
