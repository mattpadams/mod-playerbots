/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#include "GankSquadActions.h"
#include "GankSquadMgr.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "Player.h"
#include "Event.h"
#include "ServerFacade.h"

// AttackGankTargetAction

AttackGankTargetAction::AttackGankTargetAction(PlayerbotAI* botAI)
    : AttackAction(botAI, "attack gank target")
{
}

bool AttackGankTargetAction::Execute(Event event)
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad || !squad->targetPlayer)
        return false;

    Player* target = ObjectAccessor::FindPlayer(squad->targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
        return false;

    // Check if in range
    float distance = bot->GetDistance(target);
    if (distance > 30.0f)
        return false;

    // Attack the target
    return Attack(target);
}

bool AttackGankTargetAction::isUseful()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad || !squad->targetPlayer)
        return false;

    Player* target = ObjectAccessor::FindPlayer(squad->targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
        return false;

    return bot->GetDistance(target) < 30.0f;
}

// HuntGankTargetAction

HuntGankTargetAction::HuntGankTargetAction(PlayerbotAI* botAI)
    : MovementAction(botAI, "hunt gank target")
{
}

bool HuntGankTargetAction::Execute(Event event)
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad || !squad->targetPlayer)
        return false;

    Player* target = ObjectAccessor::FindPlayer(squad->targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
        return false;

    // Move toward the target
    float distance = bot->GetDistance(target);
    if (distance < 5.0f)
        return true; // Already there

    return MoveTo(target->GetMapId(), target->GetPositionX(),
                  target->GetPositionY(), target->GetPositionZ());
}

bool HuntGankTargetAction::isUseful()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    return squad->state == GANK_SQUAD_HUNTING && squad->targetPlayer;
}

// PatrolGankZoneAction

PatrolGankZoneAction::PatrolGankZoneAction(PlayerbotAI* botAI)
    : MovementAction(botAI, "patrol gank zone")
{
}

bool PatrolGankZoneAction::Execute(Event event)
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    // If this is the leader, move to patrol waypoint
    if (squad->leaderGuid == bot->GetGUID())
    {
        if (squad->patrolRoute.empty())
            return false;

        WorldPosition& waypoint = squad->patrolRoute[squad->currentWaypointIndex];

        // Check if we're at the waypoint
        WorldPosition botPos(bot);
        float distance = botPos.distance(waypoint);

        if (distance < 5.0f)
        {
            // Move to next waypoint
            squad->currentWaypointIndex =
                (squad->currentWaypointIndex + 1) % squad->patrolRoute.size();
            waypoint = squad->patrolRoute[squad->currentWaypointIndex];
        }

        return MoveTo(waypoint.getMapId(), waypoint.getX(),
                      waypoint.getY(), waypoint.getZ());
    }
    else
    {
        // Non-leader: follow the leader
        Player* leader = ObjectAccessor::FindPlayer(squad->leaderGuid);
        if (!leader || !leader->IsInWorld())
            return false;

        float distance = bot->GetDistance(leader);
        if (distance < 10.0f)
            return true; // Already close enough

        // Follow slightly behind the leader
        float angle = leader->GetOrientation() + M_PI; // Behind
        float followDistance = 5.0f;

        float x = leader->GetPositionX() + cos(angle) * followDistance;
        float y = leader->GetPositionY() + sin(angle) * followDistance;
        float z = leader->GetPositionZ();

        return MoveTo(leader->GetMapId(), x, y, z);
    }
}

bool PatrolGankZoneAction::isUseful()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    return squad->state == GANK_SQUAD_PATROL;
}

// RegroupSquadAction

RegroupSquadAction::RegroupSquadAction(PlayerbotAI* botAI)
    : MovementAction(botAI, "regroup squad")
{
}

bool RegroupSquadAction::Execute(Event event)
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    // Don't regroup if we're the leader
    if (squad->leaderGuid == bot->GetGUID())
        return false;

    Player* leader = ObjectAccessor::FindPlayer(squad->leaderGuid);
    if (!leader || !leader->IsInWorld())
        return false;

    // Move toward the leader
    return MoveTo(leader->GetMapId(), leader->GetPositionX(),
                  leader->GetPositionY(), leader->GetPositionZ());
}

bool RegroupSquadAction::isUseful()
{
    Player* bot = botAI->GetBot();
    if (!bot)
        return false;

    GankSquadInfo* squad = sGankSquadMgr->GetSquadForBot(bot->GetGUID());
    if (!squad)
        return false;

    // Only useful if we're spread out
    if (squad->leaderGuid == bot->GetGUID())
        return false;

    Player* leader = ObjectAccessor::FindPlayer(squad->leaderGuid);
    if (!leader || !leader->IsInWorld())
        return false;

    return bot->GetDistance(leader) > 50.0f;
}
