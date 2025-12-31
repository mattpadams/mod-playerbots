/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#include "GankSquadTriggers.h"
#include "GankSquadMgr.h"
#include "PlayerbotAI.h"
#include "Player.h"

GankSquadTargetNearTrigger::GankSquadTargetNearTrigger(PlayerbotAI* botAI)
    : Trigger(botAI, "gank squad target near")
{
}

bool GankSquadTargetNearTrigger::IsActive()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    if (!squad->targetPlayer)
        return false;

    // Check if target is nearby (within attack range)
    Player* target = ObjectAccessor::FindPlayer(squad->targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
        return false;

    float distance = bot->GetDistance(target);
    return distance < 30.0f; // Combat range
}

GankSquadHuntingTrigger::GankSquadHuntingTrigger(PlayerbotAI* botAI)
    : Trigger(botAI, "gank squad hunting")
{
}

bool GankSquadHuntingTrigger::IsActive()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    return squad->state == GANK_SQUAD_HUNTING;
}

GankSquadPatrolTrigger::GankSquadPatrolTrigger(PlayerbotAI* botAI)
    : Trigger(botAI, "gank squad patrol")
{
}

bool GankSquadPatrolTrigger::IsActive()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    return squad->state == GANK_SQUAD_PATROL;
}

GankSquadSpreadTrigger::GankSquadSpreadTrigger(PlayerbotAI* botAI)
    : Trigger(botAI, "gank squad spread")
{
}

bool GankSquadSpreadTrigger::IsActive()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    // Check if this bot is far from the leader
    if (squad->leaderGuid == bot->GetGUID())
        return false; // Leader doesn't need to regroup

    Player* leader = ObjectAccessor::FindPlayer(squad->leaderGuid);
    if (!leader || !leader->IsInWorld())
        return false;

    float distance = bot->GetDistance(leader);
    return distance > 50.0f; // Max spread distance
}
