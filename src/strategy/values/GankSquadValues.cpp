/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#include "GankSquadValues.h"
#include "GankSquadMgr.h"
#include "PlayerbotAI.h"
#include "Player.h"

GankSquadTargetValue::GankSquadTargetValue(PlayerbotAI* botAI)
    : UnitCalculatedValue(botAI, "gank squad target")
{
}

Unit* GankSquadTargetValue::Calculate()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return nullptr;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad || !squad->targetPlayer)
        return nullptr;

    return ObjectAccessor::FindPlayer(squad->targetPlayer);
}

GankSquadStateValue::GankSquadStateValue(PlayerbotAI* botAI)
    : CalculatedValue<uint8>(botAI, "gank squad state")
{
}

uint8 GankSquadStateValue::Calculate()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return GANK_SQUAD_DISBANDING;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return GANK_SQUAD_DISBANDING;

    return squad->state;
}

GankSquadLeaderValue::GankSquadLeaderValue(PlayerbotAI* botAI)
    : UnitCalculatedValue(botAI, "gank squad leader")
{
}

Unit* GankSquadLeaderValue::Calculate()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return nullptr;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad || !squad->leaderGuid)
        return nullptr;

    return ObjectAccessor::FindPlayer(squad->leaderGuid);
}

InGankSquadValue::InGankSquadValue(PlayerbotAI* botAI)
    : BoolCalculatedValue(botAI, "in gank squad")
{
}

bool InGankSquadValue::Calculate()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    return sGankSquadMgr->IsBotInGankSquad(bot->GetGUID());
}
