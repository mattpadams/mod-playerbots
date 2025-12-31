/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_FFAENEMYPLAYERVALUE_H
#define _PLAYERBOT_FFAENEMYPLAYERVALUE_H

#include "NamedObjectContext.h"
#include "Value.h"

class PlayerbotAI;
class Unit;

// Returns the nearest FFA hostile player
class FFAEnemyPlayerValue : public UnitCalculatedValue, public Qualified
{
public:
    FFAEnemyPlayerValue(PlayerbotAI* botAI, std::string name = "ffa enemy player")
        : UnitCalculatedValue(botAI, name), Qualified() {}

    Unit* Calculate() override;

private:
    bool AcceptUnit(Unit* unit);
};

// Returns count of FFA hostile players in range
class FFAEnemyCountValue : public Uint32CalculatedValue, public Qualified
{
public:
    FFAEnemyCountValue(PlayerbotAI* botAI, std::string name = "ffa enemy count")
        : Uint32CalculatedValue(botAI, name), Qualified() {}

    uint32 Calculate() override;
};

// Returns true if there are FFA enemies attacking the bot
class FFAUnderAttackValue : public BoolCalculatedValue
{
public:
    FFAUnderAttackValue(PlayerbotAI* botAI, std::string name = "ffa under attack")
        : BoolCalculatedValue(botAI, name) {}

    bool Calculate() override;
};

// Returns the FFA enemy that last attacked the bot
class FFALastAttackerValue : public UnitCalculatedValue
{
public:
    FFALastAttackerValue(PlayerbotAI* botAI, std::string name = "ffa last attacker")
        : UnitCalculatedValue(botAI, name) {}

    Unit* Calculate() override;
};

#endif
