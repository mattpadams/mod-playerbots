/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#include "GankSquadMgr.h"
#include "PlayerbotAIConfig.h"
#include "PlayerbotAI.h"
#include "Playerbots.h"
#include "RandomPlayerbotMgr.h"
#include "Player.h"
#include "Group.h"
#include "World.h"
#include "Log.h"

#include <algorithm>
#include <random>

// Helper function to calculate threat level from player threat data
static uint32 CalculateThreatLevel(const PlayerThreatData& data)
{
    // Threat formula:
    // KillsAgainstBots * 15 + Escapes * 10 + TimeInZoneMinutes * 2
    return (data.killsAgainstBots * 15) +
           (data.escapesFromSquads * 10) +
           (data.timeInZoneSeconds / 60 * 2);
}

GankSquadMgr::GankSquadMgr()
{
}

GankSquadMgr::~GankSquadMgr()
{
}

void GankSquadMgr::Initialize()
{
    LOG_INFO("playerbots", "GankSquadMgr: Initializing...");

    if (!IsEnabled())
    {
        LOG_INFO("playerbots", "GankSquadMgr: Disabled in config");
        return;
    }

    LOG_INFO("playerbots", "GankSquadMgr: Enabled with {} contested zones",
             sPlayerbotAIConfig->gankSquadZones.size());
}

bool GankSquadMgr::IsEnabled() const
{
    return sPlayerbotAIConfig->gankSquadEnabled;
}

void GankSquadMgr::Update(uint32 diff)
{
    if (!IsEnabled())
        return;

    std::lock_guard<std::mutex> lock(m_mutex);

    m_updateTimer += diff;
    m_spawnTimer += diff;
    m_threatDecayTimer += diff;

    // Update existing squads
    if (m_updateTimer >= UPDATE_INTERVAL)
    {
        UpdateSquads(m_updateTimer);
        m_updateTimer = 0;
    }

    // Try to spawn new squads periodically
    if (m_spawnTimer >= SPAWN_CHECK_INTERVAL)
    {
        TrySpawnNewSquad();
        m_spawnTimer = 0;
    }

    // Decay threat for players not in zones
    if (m_threatDecayTimer >= THREAT_DECAY_INTERVAL)
    {
        UpdateThreatDecay(m_threatDecayTimer);
        m_threatDecayTimer = 0;
    }
}

void GankSquadMgr::UpdateSquads(uint32 diff)
{
    std::vector<uint32> squadsToRemove;

    for (auto& [squadId, squad] : m_squads)
    {
        // Check for respawn
        if (squad.needsRespawn)
        {
            uint32 now = getMSTime();
            if (now >= squad.respawnTime)
            {
                // Try to reform the squad
                squad.needsRespawn = false;
                squad.state = GANK_SQUAD_PATROL;
                squad.members.clear();
                squad.currentSize = 0;

                // Find new bots for the squad
                auto bots = FindAvailableBots(squad.zoneId, squad.faction, squad.desiredSize);
                if (bots.size() >= sPlayerbotAIConfig->gankSquadMinSize)
                {
                    for (Player* bot : bots)
                    {
                        AddBotToSquad(squadId, bot);
                    }
                    TeleportSquadToZone(squad);
                    GeneratePatrolRoute(squad);
                }
                else
                {
                    squadsToRemove.push_back(squadId);
                }
            }
            continue;
        }

        UpdateSquadState(squad, diff);

        // Check if squad is dead
        if (!IsSquadAlive(squad))
        {
            if (squad.state != GANK_SQUAD_DISBANDING)
            {
                // Schedule respawn
                squad.needsRespawn = true;
                squad.respawnTime = getMSTime() + sPlayerbotAIConfig->gankSquadRespawnDelay * 1000;
                squad.state = GANK_SQUAD_DISBANDING;

                // Record player escape if we had a target
                if (squad.targetPlayer)
                {
                    RecordPlayerEscape(squad.targetPlayer);
                }
            }
        }
    }

    // Remove disbanded squads
    for (uint32 squadId : squadsToRemove)
    {
        DisbandSquad(squadId);
    }
}

void GankSquadMgr::UpdateSquadState(GankSquadInfo& squad, uint32 diff)
{
    switch (squad.state)
    {
        case GANK_SQUAD_PATROL:
            ProcessPatrolState(squad);
            break;
        case GANK_SQUAD_HUNTING:
            ProcessHuntingState(squad);
            break;
        case GANK_SQUAD_ENGAGING:
            ProcessEngagingState(squad);
            break;
        case GANK_SQUAD_REFORMING:
            ProcessReformingState(squad);
            break;
        case GANK_SQUAD_DISBANDING:
            // Do nothing, waiting for cleanup
            break;
    }
}

void GankSquadMgr::ProcessPatrolState(GankSquadInfo& squad)
{
    // Look for enemy players nearby
    Player* target = FindTargetPlayer(squad);
    if (target)
    {
        SetSquadTarget(squad, target);
        squad.state = GANK_SQUAD_HUNTING;
        squad.stateStartTime = getMSTime();
        LOG_DEBUG("playerbots", "GankSquadMgr: Squad {} spotted target {}, switching to HUNTING",
                  squad.squadId, target->GetName());
        return;
    }

    // Move to next patrol waypoint
    uint32 now = getMSTime();
    if (now - squad.lastPatrolMoveTime >= sPlayerbotAIConfig->gankSquadPatrolInterval)
    {
        WorldPosition nextWaypoint = GetNextPatrolWaypoint(squad);
        MoveSquadToPosition(squad, nextWaypoint);
        squad.lastPatrolMoveTime = now;
    }
}

void GankSquadMgr::ProcessHuntingState(GankSquadInfo& squad)
{
    // Check if target is still valid
    Player* target = ObjectAccessor::FindPlayer(squad.targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
    {
        ClearSquadTarget(squad);
        squad.state = GANK_SQUAD_PATROL;
        return;
    }

    // Check if target left the zone
    if (!IsContestedZone(target->GetZoneId()))
    {
        RecordPlayerEscape(squad.targetPlayer);
        ClearSquadTarget(squad);
        squad.state = GANK_SQUAD_PATROL;
        return;
    }

    // Check if we're close enough to engage
    if (IsSquadNearTarget(squad))
    {
        squad.state = GANK_SQUAD_ENGAGING;
        squad.stateStartTime = getMSTime();
        LOG_DEBUG("playerbots", "GankSquadMgr: Squad {} engaging target {}",
                  squad.squadId, target->GetName());
        return;
    }

    // Update target position and continue hunting
    squad.lastKnownPosition = WorldPosition(target);

    // Check hunt range
    WorldPosition leaderPos;
    if (Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid))
    {
        leaderPos = WorldPosition(leader);
    }
    else if (!squad.members.empty())
    {
        if (Player* firstMember = ObjectAccessor::FindPlayer(squad.members[0]))
        {
            leaderPos = WorldPosition(firstMember);
        }
    }

    float distance = leaderPos.distance(squad.lastKnownPosition);
    if (distance > sPlayerbotAIConfig->gankSquadHuntRange)
    {
        // Target too far, give up
        RecordPlayerEscape(squad.targetPlayer);
        ClearSquadTarget(squad);
        squad.state = GANK_SQUAD_PATROL;
        return;
    }

    // Move squad toward target
    MoveSquadToPosition(squad, squad.lastKnownPosition);
}

void GankSquadMgr::ProcessEngagingState(GankSquadInfo& squad)
{
    Player* target = ObjectAccessor::FindPlayer(squad.targetPlayer);
    if (!target || !target->IsInWorld() || target->isDead())
    {
        // Target killed or escaped
        if (target && target->isDead())
        {
            RecordBotKill(squad.targetPlayer);
        }
        else
        {
            RecordPlayerEscape(squad.targetPlayer);
        }
        ClearSquadTarget(squad);
        squad.state = GANK_SQUAD_REFORMING;
        squad.stateStartTime = getMSTime();
        return;
    }

    // Check if squad is spread out and needs to regroup
    if (IsSquadSpread(squad))
    {
        squad.state = GANK_SQUAD_REFORMING;
        squad.stateStartTime = getMSTime();
        return;
    }

    // Combat is handled by bot AI, just track state
    // Update threat for the player
    UpdatePlayerThreat(target);
}

void GankSquadMgr::ProcessReformingState(GankSquadInfo& squad)
{
    // Wait for squad to regroup
    uint32 now = getMSTime();
    uint32 reformTime = 15000; // 15 seconds to reform

    if (now - squad.stateStartTime >= reformTime)
    {
        // Check if squad is regrouped
        if (!IsSquadSpread(squad))
        {
            squad.state = GANK_SQUAD_PATROL;
            squad.stateStartTime = now;
            GeneratePatrolRoute(squad);
        }
    }

    // Move members toward leader
    if (Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid))
    {
        WorldPosition leaderPos(leader);
        MoveSquadToPosition(squad, leaderPos);
    }
}

void GankSquadMgr::TrySpawnNewSquad()
{
    // Check spawn chance
    float roll = (float)rand() / RAND_MAX;
    if (roll > sPlayerbotAIConfig->gankSquadSpawnChance)
        return;

    // Get contested zones with players in them
    std::vector<std::pair<uint32, TeamId>> targetZones;

    for (uint32 zoneId : sPlayerbotAIConfig->gankSquadZones)
    {
        // Check if there's a player in this zone
        // and if we already have a squad for this zone/faction combo
        // For now, just pick a random zone
        targetZones.push_back({zoneId, TEAM_ALLIANCE});
        targetZones.push_back({zoneId, TEAM_HORDE});
    }

    if (targetZones.empty())
        return;

    // Pick random zone/faction
    auto& [zoneId, faction] = targetZones[urand(0, targetZones.size() - 1)];

    // Check if we already have a squad for this zone/faction
    for (const auto& [id, squad] : m_squads)
    {
        if (squad.zoneId == zoneId && squad.faction == faction && !squad.needsRespawn)
            return; // Already have a squad
    }

    // Create new squad
    uint32 squadId = CreateSquad(zoneId, faction);
    if (squadId == 0)
    {
        LOG_DEBUG("playerbots", "GankSquadMgr: Failed to create squad for zone {} faction {}",
                  zoneId, faction == TEAM_ALLIANCE ? "Alliance" : "Horde");
    }
}

uint32 GankSquadMgr::CreateSquad(uint32 zoneId, TeamId faction)
{
    // Find available bots
    uint8 desiredSize = sPlayerbotAIConfig->gankSquadMinSize;
    auto bots = FindAvailableBots(zoneId, faction, desiredSize);

    if (bots.size() < sPlayerbotAIConfig->gankSquadMinSize)
    {
        return 0; // Not enough bots available
    }

    uint32 squadId = m_nextSquadId++;

    GankSquadInfo squad;
    squad.squadId = squadId;
    squad.zoneId = zoneId;
    squad.faction = faction;
    squad.state = GANK_SQUAD_PATROL;
    squad.desiredSize = desiredSize;
    squad.lastUpdateTime = getMSTime();
    squad.stateStartTime = getMSTime();

    m_squads[squadId] = squad;

    // Add bots to squad
    for (Player* bot : bots)
    {
        AddBotToSquad(squadId, bot);
    }

    // Set leader
    if (!m_squads[squadId].members.empty())
    {
        m_squads[squadId].leaderGuid = m_squads[squadId].members[0];
    }

    // Teleport to zone and generate patrol route
    TeleportSquadToZone(m_squads[squadId]);
    GeneratePatrolRoute(m_squads[squadId]);

    LOG_INFO("playerbots", "GankSquadMgr: Created squad {} with {} bots for zone {} ({})",
             squadId, m_squads[squadId].currentSize, zoneId,
             faction == TEAM_ALLIANCE ? "Alliance" : "Horde");

    return squadId;
}

void GankSquadMgr::DisbandSquad(uint32 squadId)
{
    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return;

    GankSquadInfo& squad = it->second;

    // Remove strategy from all bots
    for (const ObjectGuid& guid : squad.members)
    {
        if (Player* bot = ObjectAccessor::FindPlayer(guid))
        {
            RemoveGankSquadStrategy(bot);
        }
        m_botToSquad.erase(guid);
    }

    LOG_INFO("playerbots", "GankSquadMgr: Disbanded squad {}", squadId);
    m_squads.erase(it);
}

bool GankSquadMgr::AddBotToSquad(uint32 squadId, Player* bot)
{
    if (!bot)
        return false;

    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return false;

    GankSquadInfo& squad = it->second;

    // Check if bot is already in a squad
    if (m_botToSquad.find(bot->GetGUID()) != m_botToSquad.end())
        return false;

    squad.members.push_back(bot->GetGUID());
    squad.currentSize++;
    m_botToSquad[bot->GetGUID()] = squadId;

    // Apply gank squad strategy
    ApplyGankSquadStrategy(bot);

    return true;
}

void GankSquadMgr::RemoveBotFromSquad(ObjectGuid botGuid)
{
    auto it = m_botToSquad.find(botGuid);
    if (it == m_botToSquad.end())
        return;

    uint32 squadId = it->second;
    auto squadIt = m_squads.find(squadId);
    if (squadIt != m_squads.end())
    {
        GankSquadInfo& squad = squadIt->second;
        squad.members.erase(
            std::remove(squad.members.begin(), squad.members.end(), botGuid),
            squad.members.end());
        squad.currentSize = squad.members.size();

        // Update leader if necessary
        if (squad.leaderGuid == botGuid && !squad.members.empty())
        {
            squad.leaderGuid = squad.members[0];
        }
    }

    if (Player* bot = ObjectAccessor::FindPlayer(botGuid))
    {
        RemoveGankSquadStrategy(bot);
    }

    m_botToSquad.erase(it);
}

void GankSquadMgr::ApplyGankSquadStrategy(Player* bot)
{
    if (!bot)
        return;

    PlayerbotAI* ai = GET_PLAYERBOT_AI(bot);
    if (!ai)
        return;

    // Add gank squad strategy
    ai->ChangeStrategy("+ganksquad", BotState::BOT_STATE_NON_COMBAT);
    ai->ChangeStrategy("+pvp", BotState::BOT_STATE_COMBAT);
}

void GankSquadMgr::RemoveGankSquadStrategy(Player* bot)
{
    if (!bot)
        return;

    PlayerbotAI* ai = GET_PLAYERBOT_AI(bot);
    if (!ai)
        return;

    ai->ChangeStrategy("-ganksquad", BotState::BOT_STATE_NON_COMBAT);
}

std::vector<Player*> GankSquadMgr::FindAvailableBots(uint32 zoneId, TeamId faction, uint8 count)
{
    std::vector<Player*> result;

    // Get level range for zone
    uint32 minLevel = sPlayerbotAIConfig->gankSquadMinLevel;
    uint32 maxLevel = sPlayerbotAIConfig->gankSquadMaxLevel;

    // Adjust based on zone if we have zone level data
    auto zoneBrackets = sPlayerbotAIConfig->zoneBrackets;
    auto it = zoneBrackets.find(zoneId);
    if (it != zoneBrackets.end())
    {
        minLevel = std::max(minLevel, it->second.first);
        maxLevel = std::min(maxLevel, it->second.second);
    }

    // Get all random bots
    auto allBots = sRandomPlayerbotMgr->GetAllBots();
    std::vector<Player*> candidates;

    for (auto& [guid, bot] : allBots)
    {
        if (!bot || !bot->IsInWorld())
            continue;

        // Check faction
        if (bot->GetTeamId() != faction)
            continue;

        // Check level
        if (bot->GetLevel() < minLevel || bot->GetLevel() > maxLevel)
            continue;

        // Check if already in a squad
        if (m_botToSquad.find(bot->GetGUID()) != m_botToSquad.end())
            continue;

        // Check if in battleground
        if (bot->InBattleground())
            continue;

        // Check if in a group with a real player
        if (Group* group = bot->GetGroup())
        {
            bool hasRealPlayer = false;
            for (GroupReference* ref = group->GetFirstMember(); ref; ref = ref->next())
            {
                if (Player* member = ref->GetSource())
                {
                    if (!GET_PLAYERBOT_AI(member))
                    {
                        hasRealPlayer = true;
                        break;
                    }
                }
            }
            if (hasRealPlayer)
                continue;
        }

        // Check if bot is dead
        if (bot->isDead())
            continue;

        candidates.push_back(bot);
    }

    // Shuffle and take first 'count' bots
    std::random_device rd;
    std::mt19937 g(rd());
    std::shuffle(candidates.begin(), candidates.end(), g);

    for (size_t i = 0; i < std::min((size_t)count, candidates.size()); ++i)
    {
        result.push_back(candidates[i]);
    }

    return result;
}

GankSquadInfo* GankSquadMgr::GetSquadForBot(ObjectGuid botGuid)
{
    auto it = m_botToSquad.find(botGuid);
    if (it == m_botToSquad.end())
        return nullptr;

    auto squadIt = m_squads.find(it->second);
    if (squadIt == m_squads.end())
        return nullptr;

    return &squadIt->second;
}

GankSquadInfo* GankSquadMgr::GetSquad(uint32 squadId)
{
    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return nullptr;
    return &it->second;
}

bool GankSquadMgr::IsBotInGankSquad(ObjectGuid botGuid) const
{
    return m_botToSquad.find(botGuid) != m_botToSquad.end();
}

ObjectGuid GankSquadMgr::GetSquadTarget(uint32 squadId) const
{
    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return ObjectGuid::Empty;
    return it->second.targetPlayer;
}

ObjectGuid GankSquadMgr::GetSquadLeader(uint32 squadId) const
{
    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return ObjectGuid::Empty;
    return it->second.leaderGuid;
}

GankSquadState GankSquadMgr::GetSquadState(uint32 squadId) const
{
    auto it = m_squads.find(squadId);
    if (it == m_squads.end())
        return GANK_SQUAD_DISBANDING;
    return it->second.state;
}

Player* GankSquadMgr::FindTargetPlayer(GankSquadInfo& squad)
{
    // Get squad leader position
    Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid);
    if (!leader)
        return nullptr;

    WorldPosition leaderPos(leader);
    float searchRange = sPlayerbotAIConfig->sightDistance;

    Player* bestTarget = nullptr;
    uint32 highestThreat = 0;

    // Search for enemy players
    for (auto& [guid, threatData] : m_playerThreats)
    {
        Player* player = ObjectAccessor::FindPlayer(guid);
        if (!player || !player->IsInWorld() || player->isDead())
            continue;

        // Check faction
        if (player->GetTeamId() == squad.faction)
            continue;

        // Check zone
        if (player->GetZoneId() != squad.zoneId)
            continue;

        // Check PvP flag
        if (!player->IsPvP())
            continue;

        // Check distance
        WorldPosition playerPos(player);
        if (leaderPos.distance(playerPos) > searchRange)
            continue;

        // Prefer higher threat targets
        if (threatData.threatLevel > highestThreat)
        {
            highestThreat = threatData.threatLevel;
            bestTarget = player;
        }
    }

    // Also check for any enemy players in range even without threat data
    if (!bestTarget)
    {
        // Use simple range check from leader
        Map* map = leader->GetMap();
        if (map)
        {
            // This is a simplified search - in production you'd use
            // map->GetPlayers() or similar
        }
    }

    return bestTarget;
}

void GankSquadMgr::SetSquadTarget(GankSquadInfo& squad, Player* target)
{
    if (!target)
        return;

    squad.targetPlayer = target->GetGUID();
    squad.lastKnownPosition = WorldPosition(target);

    // Update or create threat data
    if (m_playerThreats.find(target->GetGUID()) == m_playerThreats.end())
    {
        PlayerThreatData data;
        data.playerGuid = target->GetGUID();
        data.zoneId = target->GetZoneId();
        data.lastSeenTimestamp = getMSTime();
        data.currentSquadId = squad.squadId;
        m_playerThreats[target->GetGUID()] = data;
    }
    else
    {
        m_playerThreats[target->GetGUID()].currentSquadId = squad.squadId;
    }

    // Adjust squad size based on threat
    uint32 threat = GetPlayerThreatLevel(target->GetGUID());
    squad.desiredSize = CalculateSquadSize(threat);
}

void GankSquadMgr::ClearSquadTarget(GankSquadInfo& squad)
{
    if (squad.targetPlayer)
    {
        auto it = m_playerThreats.find(squad.targetPlayer);
        if (it != m_playerThreats.end() && it->second.currentSquadId == squad.squadId)
        {
            it->second.currentSquadId = 0;
        }
    }
    squad.targetPlayer = ObjectGuid::Empty;
}

void GankSquadMgr::GeneratePatrolRoute(GankSquadInfo& squad)
{
    squad.patrolRoute.clear();
    squad.currentWaypointIndex = 0;

    // Generate random patrol points within the zone
    // This is simplified - in production you'd use actual zone boundaries
    // and path validation

    // Use patrol center as base
    if (squad.patrolCenter.getMapId() == 0)
    {
        // Need to set patrol center from zone data
        // For now, just use current leader position
        if (Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid))
        {
            squad.patrolCenter = WorldPosition(leader);
        }
    }

    // Generate 5-8 waypoints in a rough circle
    uint8 waypointCount = urand(5, 8);
    float radius = 100.0f; // 100 yards patrol radius

    for (uint8 i = 0; i < waypointCount; ++i)
    {
        float angle = (2 * M_PI * i) / waypointCount;
        float x = squad.patrolCenter.getX() + cos(angle) * radius;
        float y = squad.patrolCenter.getY() + sin(angle) * radius;
        float z = squad.patrolCenter.getZ();

        WorldPosition waypoint(squad.patrolCenter.getMapId(), x, y, z, 0.0f);
        squad.patrolRoute.push_back(waypoint);
    }
}

WorldPosition GankSquadMgr::GetNextPatrolWaypoint(GankSquadInfo& squad)
{
    if (squad.patrolRoute.empty())
    {
        GeneratePatrolRoute(squad);
    }

    if (squad.patrolRoute.empty())
    {
        return squad.patrolCenter;
    }

    WorldPosition waypoint = squad.patrolRoute[squad.currentWaypointIndex];
    squad.currentWaypointIndex = (squad.currentWaypointIndex + 1) % squad.patrolRoute.size();

    return waypoint;
}

void GankSquadMgr::UpdatePlayerThreat(Player* player)
{
    if (!player)
        return;

    auto& data = m_playerThreats[player->GetGUID()];
    data.playerGuid = player->GetGUID();
    data.zoneId = player->GetZoneId();
    data.lastSeenTimestamp = getMSTime();
    data.lastKnownPosition = WorldPosition(player);

    // Time in zone adds threat (calculated in decay function)
}

void GankSquadMgr::RecordPlayerKill(ObjectGuid playerGuid)
{
    auto& data = m_playerThreats[playerGuid];
    data.killsAgainstBots++;
    data.threatLevel = CalculateThreatLevel(data);

    LOG_DEBUG("playerbots", "GankSquadMgr: Player {} killed a bot, threat now {}",
              playerGuid.GetCounter(), data.threatLevel);
}

void GankSquadMgr::RecordPlayerEscape(ObjectGuid playerGuid)
{
    auto& data = m_playerThreats[playerGuid];
    data.escapesFromSquads++;
    data.threatLevel = CalculateThreatLevel(data);

    LOG_DEBUG("playerbots", "GankSquadMgr: Player {} escaped, threat now {}",
              playerGuid.GetCounter(), data.threatLevel);
}

void GankSquadMgr::RecordBotKill(ObjectGuid playerGuid)
{
    // Player was killed by the squad - reduce threat slightly
    auto it = m_playerThreats.find(playerGuid);
    if (it != m_playerThreats.end())
    {
        // Reduce threat by 10%
        it->second.threatLevel = (it->second.threatLevel * 9) / 10;
    }
}

uint32 GankSquadMgr::GetPlayerThreatLevel(ObjectGuid playerGuid) const
{
    auto it = m_playerThreats.find(playerGuid);
    if (it == m_playerThreats.end())
        return 0;
    return it->second.threatLevel;
}

PlayerThreatData* GankSquadMgr::GetPlayerThreat(ObjectGuid playerGuid)
{
    auto it = m_playerThreats.find(playerGuid);
    if (it == m_playerThreats.end())
        return nullptr;
    return &it->second;
}

uint8 GankSquadMgr::CalculateSquadSize(uint32 threatLevel) const
{
    // Squad size scaling:
    // 0-20:   2-3 bots
    // 21-40:  3-4 bots
    // 41-60:  4-6 bots
    // 61-80:  6-8 bots
    // 81+:    8-10 bots

    uint8 minSize = sPlayerbotAIConfig->gankSquadMinSize;
    uint8 maxSize = sPlayerbotAIConfig->gankSquadMaxSize;

    if (threatLevel <= 20)
        return std::min(maxSize, std::max(minSize, (uint8)3));
    else if (threatLevel <= 40)
        return std::min(maxSize, std::max(minSize, (uint8)4));
    else if (threatLevel <= 60)
        return std::min(maxSize, std::max(minSize, (uint8)6));
    else if (threatLevel <= 80)
        return std::min(maxSize, std::max(minSize, (uint8)8));
    else
        return maxSize;
}

void GankSquadMgr::UpdateThreatDecay(uint32 diff)
{
    uint32 decayRate = sPlayerbotAIConfig->gankSquadThreatDecayRate;
    uint32 now = getMSTime();

    std::vector<ObjectGuid> toRemove;

    for (auto& [guid, data] : m_playerThreats)
    {
        Player* player = ObjectAccessor::FindPlayer(guid);

        // If player is online and in a contested zone, add time
        if (player && player->IsInWorld() && IsContestedZone(player->GetZoneId()))
        {
            data.timeInZoneSeconds += THREAT_DECAY_INTERVAL / 1000;
            data.lastSeenTimestamp = now;
        }
        else
        {
            // Decay threat
            if (data.threatLevel > decayRate)
                data.threatLevel -= decayRate;
            else
                data.threatLevel = 0;
        }

        // Recalculate threat level
        data.threatLevel = CalculateThreatLevel(data);

        // Remove stale entries
        if (data.threatLevel == 0 && (now - data.lastSeenTimestamp) > 3600000) // 1 hour
        {
            toRemove.push_back(guid);
        }
    }

    for (const ObjectGuid& guid : toRemove)
    {
        m_playerThreats.erase(guid);
    }
}

bool GankSquadMgr::IsContestedZone(uint32 zoneId) const
{
    return sPlayerbotAIConfig->IsGankSquadZone(zoneId);
}

std::vector<uint32> GankSquadMgr::GetContestedZones() const
{
    return sPlayerbotAIConfig->gankSquadZones;
}

bool GankSquadMgr::IsSquadAlive(const GankSquadInfo& squad) const
{
    if (squad.members.empty())
        return false;

    // Check if at least one member is alive
    for (const ObjectGuid& guid : squad.members)
    {
        Player* bot = ObjectAccessor::FindPlayer(guid);
        if (bot && bot->IsInWorld() && !bot->isDead())
            return true;
    }
    return false;
}

bool GankSquadMgr::IsSquadNearTarget(const GankSquadInfo& squad) const
{
    if (!squad.targetPlayer)
        return false;

    Player* target = ObjectAccessor::FindPlayer(squad.targetPlayer);
    if (!target)
        return false;

    WorldPosition targetPos(target);

    // Check if at least half the squad is within engagement range
    uint32 nearCount = 0;
    for (const ObjectGuid& guid : squad.members)
    {
        Player* bot = ObjectAccessor::FindPlayer(guid);
        if (!bot || !bot->IsInWorld() || bot->isDead())
            continue;

        WorldPosition botPos(bot);
        if (botPos.distance(targetPos) < 30.0f) // Combat range
        {
            nearCount++;
        }
    }

    return nearCount >= (squad.members.size() / 2);
}

bool GankSquadMgr::IsSquadSpread(const GankSquadInfo& squad) const
{
    if (squad.members.size() < 2)
        return false;

    Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid);
    if (!leader)
        return true;

    WorldPosition leaderPos(leader);
    float maxDistance = 50.0f; // Max allowed spread

    for (const ObjectGuid& guid : squad.members)
    {
        if (guid == squad.leaderGuid)
            continue;

        Player* bot = ObjectAccessor::FindPlayer(guid);
        if (!bot || !bot->IsInWorld() || bot->isDead())
            continue;

        WorldPosition botPos(bot);
        if (leaderPos.distance(botPos) > maxDistance)
            return true;
    }

    return false;
}

void GankSquadMgr::TeleportSquadToZone(GankSquadInfo& squad)
{
    // For squads, we rely on bots already being in the zone when recruited
    // The squad formation process already selects bots that are in the target zone
    // Just update patrol center based on current leader position
    if (Player* leader = ObjectAccessor::FindPlayer(squad.leaderGuid))
    {
        squad.patrolCenter = WorldPosition(leader);
    }
}

void GankSquadMgr::MoveSquadToPosition(GankSquadInfo& squad, const WorldPosition& pos)
{
    // This will be handled by the GankSquadStrategy/Actions
    // Just update the target position for reference
    squad.patrolCenter = pos;
}
