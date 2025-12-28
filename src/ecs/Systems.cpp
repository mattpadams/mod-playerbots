/*
 * ECS Systems Implementation
 *
 * Batch processing systems for efficient bot updates.
 */

#include "Systems.h"
#include "ValueCache.h"
#include "Player.h"
#include "PlayerbotAI.h"
#include "Timer.h"
#include "Log.h"
#include <algorithm>

namespace ecs {

// Static metrics initialization
SystemMetrics MovementSystem::s_metrics = {"Movement"};
SystemMetrics SpatialUpdateSystem::s_metrics = {"Spatial"};
SystemMetrics CombatSyncSystem::s_metrics = {"CombatSync"};
SystemMetrics ThreatSystem::s_metrics = {"Threat"};
SystemMetrics TargetSelectionSystem::s_metrics = {"TargetSelection"};
SystemMetrics AIStateSystem::s_metrics = {"AIState"};
SystemMetrics SquadSystem::s_metrics = {"Squad"};

// =============================================================================
// MovementSystem
// =============================================================================

void MovementSystem::Update(Registry& registry, float deltaTime)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    // Get direct pointers to component arrays for cache efficiency
    ComponentArray<Position>* positions = registry.GetComponentArray<Position>();
    ComponentArray<Velocity>* velocities = registry.GetComponentArray<Velocity>();

    if (!positions || !velocities)
        return;

    // Iterate velocity array (typically smaller than position)
    velocities->ForEach([&](EntityId id, Velocity& vel) {
        if (!vel.isMoving)
            return;

        if (Position* pos = positions->Get(id))
        {
            pos->x += vel.dx * deltaTime;
            pos->y += vel.dy * deltaTime;
            pos->z += vel.dz * deltaTime;
            count++;
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// =============================================================================
// SpatialUpdateSystem
// =============================================================================

void SpatialUpdateSystem::Update(Registry& registry)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    constexpr float CELL_SIZE = 32.0f;

    registry.ForEach<Position>([&](EntityId id, Position& pos) {
        int32_t newCellX = static_cast<int32_t>(pos.x / CELL_SIZE);
        int32_t newCellY = static_cast<int32_t>(pos.y / CELL_SIZE);

        if (pos.cellX != newCellX || pos.cellY != newCellY)
        {
            pos.cellX = newCellX;
            pos.cellY = newCellY;
            count++;
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// Spatial index for neighbor queries (local to this file)
struct EcsSpatialCell
{
    uint64_t key;  // Packed (mapId << 32) | (cellX << 16) | cellY
    std::vector<EntityId> entities;
};

static std::unordered_map<uint64_t, EcsSpatialCell> s_spatialIndex;

void SpatialUpdateSystem::RebuildIndex(Registry& registry)
{
    uint32_t startTime = getMSTime();

    s_spatialIndex.clear();

    registry.ForEach<Position>([](EntityId id, Position& pos) {
        uint64_t key = (static_cast<uint64_t>(pos.mapId) << 32) |
                       (static_cast<uint64_t>(static_cast<uint16_t>(pos.cellX)) << 16) |
                       static_cast<uint64_t>(static_cast<uint16_t>(pos.cellY));

        s_spatialIndex[key].entities.push_back(id);
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(static_cast<uint32_t>(s_spatialIndex.size()), elapsed);
}

std::vector<EntityId> SpatialUpdateSystem::FindNearby(
    Registry& registry,
    float x, float y, float z,
    uint32_t mapId,
    float radius)
{
    std::vector<EntityId> result;
    constexpr float CELL_SIZE = 32.0f;

    int32_t centerCellX = static_cast<int32_t>(x / CELL_SIZE);
    int32_t centerCellY = static_cast<int32_t>(y / CELL_SIZE);
    int32_t cellRadius = static_cast<int32_t>(radius / CELL_SIZE) + 1;

    float radiusSq = radius * radius;

    // Check all cells in range
    for (int32_t dx = -cellRadius; dx <= cellRadius; ++dx)
    {
        for (int32_t dy = -cellRadius; dy <= cellRadius; ++dy)
        {
            int32_t cellX = centerCellX + dx;
            int32_t cellY = centerCellY + dy;

            uint64_t key = (static_cast<uint64_t>(mapId) << 32) |
                           (static_cast<uint64_t>(static_cast<uint16_t>(cellX)) << 16) |
                           static_cast<uint64_t>(static_cast<uint16_t>(cellY));

            auto it = s_spatialIndex.find(key);
            if (it == s_spatialIndex.end())
                continue;

            for (EntityId id : it->second.entities)
            {
                if (const Position* pos = registry.GetComponent<Position>(id))
                {
                    float distSq = (pos->x - x) * (pos->x - x) +
                                   (pos->y - y) * (pos->y - y) +
                                   (pos->z - z) * (pos->z - z);

                    if (distSq <= radiusSq)
                    {
                        result.push_back(id);
                    }
                }
            }
        }
    }

    return result;
}

// =============================================================================
// CombatSyncSystem
// =============================================================================

void CombatSyncSystem::Update(Registry& registry)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    ComponentArray<BotLink>* links = registry.GetComponentArray<BotLink>();
    ComponentArray<CombatState>* combats = registry.GetComponentArray<CombatState>();

    if (!links || !combats)
        return;

    links->ForEach([&](EntityId id, BotLink& link) {
        if (!link.player)
            return;

        if (CombatState* combat = combats->Get(id))
        {
            SyncSystem::SyncCombatState(link.player, *combat);
            count++;
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// =============================================================================
// ThreatSystem
// =============================================================================

void ThreatSystem::Update(Registry& registry)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    // For now, just count entities with threat lists
    registry.ForEach<ThreatList>([&](EntityId id, ThreatList& threats) {
        // TODO: Sync threat from WoW ThreatManager
        // This is a placeholder for future implementation
        count++;
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// =============================================================================
// TargetSelectionSystem
// =============================================================================

void TargetSelectionSystem::Update(Registry& registry)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    // Iterate entities in combat that need target updates
    registry.ForEach<CombatState>([&](EntityId id, CombatState& combat) {
        if (!combat.inCombat)
            return;

        if (Target* target = registry.GetComponent<Target>(id))
        {
            // TODO: Implement ECS-based target selection
            // For now, target selection still uses existing PlayerbotAI logic
            count++;
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// =============================================================================
// AIStateSystem
// =============================================================================

void AIStateSystem::Update(Registry& registry, uint32_t now)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    registry.ForEach<AIState>([&](EntityId id, AIState& ai) {
        // Check if update is due
        if (now < ai.nextUpdateTime)
            return;

        // Schedule next update
        ai.nextUpdateTime = now + ai.updateInterval;
        ai.lastUpdateTime = now;

        // Get bot link to access PlayerbotAI
        if (const BotLink* link = registry.GetComponent<BotLink>(id))
        {
            if (link->botAI)
            {
                // TODO: Eventually move AI logic to ECS
                // For now, the existing Engine handles AI updates
                count++;
            }
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

// =============================================================================
// SquadSystem
// =============================================================================

void SquadSystem::UpdateFormations(Registry& registry)
{
    uint32_t startTime = getMSTime();
    uint32_t count = 0;

    registry.ForEach<SquadMember>([&](EntityId id, SquadMember& member) {
        if (member.isLeader || !member.squadLeader.IsValid())
            return;

        // Get leader position
        if (const Position* leaderPos = registry.GetComponent<Position>(member.squadLeader))
        {
            // Calculate follow position based on formation
            float angle = member.followAngle;
            float dist = member.followDistance;

            // TODO: Update target position based on formation
            count++;
        }
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    s_metrics.RecordUpdate(count, elapsed);
}

void SquadSystem::PropagateCommands(Registry& registry)
{
    // TODO: Implement command propagation from leaders to followers
    // This is for hierarchical AI where squad leaders make decisions
    // and followers execute simplified versions
}

// =============================================================================
// BatchUpdateManager
// =============================================================================

void BatchUpdateManager::Update(uint32_t diff)
{
    uint32_t startTime = getMSTime();
    uint32_t now = startTime;

    Registry& registry = sBotRegistry.GetRegistry();

    // Position sync (high frequency)
    if (now - m_lastPositionSync >= m_config.positionSyncInterval)
    {
        uint32_t syncStart = getMSTime();
        sBotRegistry.SyncFromWoW();
        m_lastTiming.syncMs = static_cast<float>(getMSTimeDiff(syncStart, getMSTime()));
        m_lastPositionSync = now;
    }

    // Combat sync
    if (now - m_lastCombatSync >= m_config.combatSyncInterval)
    {
        uint32_t combatStart = getMSTime();
        CombatSyncSystem::Update(registry);
        m_lastTiming.combatMs = static_cast<float>(getMSTimeDiff(combatStart, getMSTime()));
        m_lastCombatSync = now;
    }

    // Movement update
    {
        uint32_t moveStart = getMSTime();
        float deltaTime = static_cast<float>(diff) / 1000.0f;
        MovementSystem::Update(registry, deltaTime);
        m_lastTiming.movementMs = static_cast<float>(getMSTimeDiff(moveStart, getMSTime()));
    }

    // Value cache update (high frequency for responsive combat)
    if (now - m_lastVitalsSync >= m_config.vitalsSyncInterval)
    {
        ValueCacheSystem::Update(registry, now);
        m_lastVitalsSync = now;
    }

    // Spatial index rebuild (low frequency)
    if (now - m_lastSpatialRebuild >= m_config.spatialRebuildInterval)
    {
        SpatialUpdateSystem::RebuildIndex(registry);
        m_lastSpatialRebuild = now;
    }

    // AI updates
    if (now - m_lastAIUpdate >= m_config.aiUpdateInterval)
    {
        uint32_t aiStart = getMSTime();
        AIStateSystem::Update(registry, now);
        SquadSystem::UpdateFormations(registry);
        m_lastTiming.aiMs = static_cast<float>(getMSTimeDiff(aiStart, getMSTime()));
        m_lastAIUpdate = now;
    }

    // Metrics update (very low frequency)
    if (now - m_lastMetricsUpdate >= m_config.metricsUpdateInterval)
    {
        sBotRegistry.UpdateMetrics();
        m_lastMetricsUpdate = now;
    }

    m_lastTiming.totalMs = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
    m_lastTiming.botsUpdated = static_cast<uint32_t>(sBotRegistry.GetBotCount());
}

std::vector<const SystemMetrics*> BatchUpdateManager::GetAllMetrics() const
{
    return {
        &MovementSystem::GetMetrics(),
        &SpatialUpdateSystem::GetMetrics(),
        &CombatSyncSystem::GetMetrics(),
        &ThreatSystem::GetMetrics(),
        &TargetSelectionSystem::GetMetrics(),
        &AIStateSystem::GetMetrics(),
        &SquadSystem::GetMetrics()
    };
}

} // namespace ecs
