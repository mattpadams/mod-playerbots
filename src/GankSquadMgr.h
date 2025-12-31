/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license
 */

#ifndef _PLAYERBOT_GANKSQUADMGR_H
#define _PLAYERBOT_GANKSQUADMGR_H

#include "Common.h"
#include "ObjectGuid.h"
#include "SharedDefines.h"
#include "TravelMgr.h"

#include <map>
#include <vector>
#include <mutex>

class Player;
class PlayerbotAI;

enum GankSquadState : uint8
{
    GANK_SQUAD_PATROL = 0,      // Patrolling zone waypoints
    GANK_SQUAD_HUNTING = 1,     // Moving toward detected player
    GANK_SQUAD_ENGAGING = 2,    // In combat with target
    GANK_SQUAD_REFORMING = 3,   // Regrouping after combat
    GANK_SQUAD_DISBANDING = 4   // Squad is being disbanded
};

struct PlayerThreatData
{
    ObjectGuid playerGuid;
    uint32 zoneId = 0;
    uint32 threatLevel = 0;           // 0-100+ scale
    uint32 killsAgainstBots = 0;      // Times killed bot squad members (+15 each)
    uint32 escapesFromSquads = 0;     // Times escaped after being engaged (+10 each)
    uint32 timeInZoneSeconds = 0;     // Cumulative time in contested zones (+2 per minute)
    uint32 lastSeenTimestamp = 0;
    WorldPosition lastKnownPosition;
    uint32 currentSquadId = 0;        // Squad currently hunting this player (0 = none)
};

struct GankSquadInfo
{
    uint32 squadId = 0;
    std::vector<ObjectGuid> members;
    ObjectGuid targetPlayer;
    ObjectGuid leaderGuid;
    uint32 zoneId = 0;
    TeamId faction = TEAM_NEUTRAL;
    WorldPosition patrolCenter;
    std::vector<WorldPosition> patrolRoute;
    WorldPosition lastKnownPosition;  // Last known target position
    uint32 currentWaypointIndex = 0;
    GankSquadState state = GANK_SQUAD_PATROL;
    uint32 lastUpdateTime = 0;
    uint32 lastPatrolMoveTime = 0;
    uint32 stateStartTime = 0;
    uint8 desiredSize = 2;            // Based on target threat level
    uint8 currentSize = 0;
    bool needsRespawn = false;
    uint32 respawnTime = 0;
};

class GankSquadMgr
{
public:
    GankSquadMgr();
    ~GankSquadMgr();

    static GankSquadMgr* instance()
    {
        static GankSquadMgr instance;
        return &instance;
    }

    void Initialize();
    void Update(uint32 diff);

    // Squad lifecycle
    uint32 CreateSquad(uint32 zoneId, TeamId faction);
    void DisbandSquad(uint32 squadId);
    bool AddBotToSquad(uint32 squadId, Player* bot);
    void RemoveBotFromSquad(ObjectGuid botGuid);
    void ApplyGankSquadStrategy(Player* bot);
    void RemoveGankSquadStrategy(Player* bot);

    // Squad queries
    GankSquadInfo* GetSquadForBot(ObjectGuid botGuid);
    GankSquadInfo* GetSquad(uint32 squadId);
    bool IsBotInGankSquad(ObjectGuid botGuid) const;
    ObjectGuid GetSquadTarget(uint32 squadId) const;
    ObjectGuid GetSquadLeader(uint32 squadId) const;
    GankSquadState GetSquadState(uint32 squadId) const;

    // Player threat tracking
    void UpdatePlayerThreat(Player* player);
    void RecordPlayerKill(ObjectGuid playerGuid);      // Player killed a bot
    void RecordPlayerEscape(ObjectGuid playerGuid);    // Player escaped engagement
    void RecordBotKill(ObjectGuid playerGuid);         // Bot killed the player
    uint32 GetPlayerThreatLevel(ObjectGuid playerGuid) const;
    PlayerThreatData* GetPlayerThreat(ObjectGuid playerGuid);

    // Zone management
    bool IsContestedZone(uint32 zoneId) const;
    std::vector<uint32> GetContestedZones() const;

    // Configuration
    bool IsEnabled() const;

private:
    // Squad management
    void UpdateSquads(uint32 diff);
    void UpdateSquadState(GankSquadInfo& squad, uint32 diff);
    void ProcessPatrolState(GankSquadInfo& squad);
    void ProcessHuntingState(GankSquadInfo& squad);
    void ProcessEngagingState(GankSquadInfo& squad);
    void ProcessReformingState(GankSquadInfo& squad);

    // Squad formation
    void TrySpawnNewSquad();
    std::vector<Player*> FindAvailableBots(uint32 zoneId, TeamId faction, uint8 count);
    void FormSquadGroup(GankSquadInfo& squad);
    uint8 CalculateSquadSize(uint32 threatLevel) const;

    // Target detection
    Player* FindTargetPlayer(GankSquadInfo& squad);
    void SetSquadTarget(GankSquadInfo& squad, Player* target);
    void ClearSquadTarget(GankSquadInfo& squad);

    // Patrol routes
    void GeneratePatrolRoute(GankSquadInfo& squad);
    WorldPosition GetNextPatrolWaypoint(GankSquadInfo& squad);

    // Threat management
    void UpdateThreatDecay(uint32 diff);
    void CleanupOldThreatData();

    // Helper methods
    bool IsSquadAlive(const GankSquadInfo& squad) const;
    bool IsSquadNearTarget(const GankSquadInfo& squad) const;
    bool IsSquadSpread(const GankSquadInfo& squad) const;
    void TeleportSquadToZone(GankSquadInfo& squad);
    void MoveSquadToPosition(GankSquadInfo& squad, const WorldPosition& pos);

private:
    std::map<uint32, GankSquadInfo> m_squads;
    std::map<ObjectGuid, PlayerThreatData> m_playerThreats;
    std::map<ObjectGuid, uint32> m_botToSquad;  // Bot GUID -> Squad ID

    uint32 m_nextSquadId = 1;
    uint32 m_updateTimer = 0;
    uint32 m_spawnTimer = 0;
    uint32 m_threatDecayTimer = 0;

    static const uint32 UPDATE_INTERVAL = 5000;        // 5 seconds
    static const uint32 SPAWN_CHECK_INTERVAL = 30000;  // 30 seconds
    static const uint32 THREAT_DECAY_INTERVAL = 60000; // 1 minute

    mutable std::mutex m_mutex;
};

#define sGankSquadMgr GankSquadMgr::instance()

#endif  // _PLAYERBOT_GANKSQUADMGR_H
