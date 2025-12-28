/*
 * ECS Systems - Batch processing systems for bot updates
 *
 * Systems operate on entities with specific component combinations.
 * They process data in batches for cache efficiency.
 *
 * Design principles:
 * - Systems are stateless functions operating on component data
 * - Process all matching entities in tight loops
 * - Minimize branching within loops
 * - Use SIMD where applicable for hot paths
 */

#ifndef _PLAYERBOT_ECS_SYSTEMS_H
#define _PLAYERBOT_ECS_SYSTEMS_H

#include "BotRegistry.h"
#include <chrono>
#include <vector>

namespace ecs {

/*
 * SystemMetrics - Performance tracking for systems
 */
struct SystemMetrics
{
    const char* name = nullptr;
    uint32_t entitiesProcessed = 0;
    float lastUpdateMs = 0.0f;
    float avgUpdateMs = 0.0f;
    float maxUpdateMs = 0.0f;
    uint32_t updateCount = 0;

    void RecordUpdate(uint32_t entities, float timeMs)
    {
        entitiesProcessed = entities;
        lastUpdateMs = timeMs;
        maxUpdateMs = std::max(maxUpdateMs, timeMs);
        avgUpdateMs = avgUpdateMs * 0.95f + timeMs * 0.05f;  // EMA
        updateCount++;
    }
};

/*
 * ========================================================================
 * MOVEMENT SYSTEMS
 * ========================================================================
 */

/*
 * MovementSystem - Update positions based on velocity
 *
 * Processes entities with: Position, Velocity
 */
class MovementSystem
{
public:
    static void Update(Registry& registry, float deltaTime);
    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * SpatialUpdateSystem - Update spatial partitioning cells
 *
 * Processes entities with: Position (where cellX/cellY changed)
 */
class SpatialUpdateSystem
{
public:
    // Update cell coordinates for all positions
    static void Update(Registry& registry);

    // Build spatial index for quick neighbor queries
    static void RebuildIndex(Registry& registry);

    // Find entities near a position
    static std::vector<EntityId> FindNearby(
        Registry& registry,
        float x, float y, float z,
        uint32_t mapId,
        float radius
    );

    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * ========================================================================
 * COMBAT SYSTEMS
 * ========================================================================
 */

/*
 * CombatSyncSystem - Sync combat state from WoW
 *
 * Processes entities with: BotLink, CombatState
 */
class CombatSyncSystem
{
public:
    static void Update(Registry& registry);
    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * ThreatSystem - Update threat lists
 *
 * Processes entities with: BotLink, ThreatList, CombatState
 */
class ThreatSystem
{
public:
    static void Update(Registry& registry);
    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * TargetSelectionSystem - Choose combat targets
 *
 * Processes entities with: CombatState, Target, BotRole
 */
class TargetSelectionSystem
{
public:
    static void Update(Registry& registry);
    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * ========================================================================
 * AI SYSTEMS
 * ========================================================================
 */

/*
 * AIStateSystem - Update AI state machine
 *
 * Processes entities with: AIState, BotLink
 */
class AIStateSystem
{
public:
    static void Update(Registry& registry, uint32_t now);
    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * SquadSystem - Hierarchical AI coordination
 *
 * Processes squad leaders and their followers
 */
class SquadSystem
{
public:
    // Update squad formations
    static void UpdateFormations(Registry& registry);

    // Propagate commands from leaders to followers
    static void PropagateCommands(Registry& registry);

    static SystemMetrics& GetMetrics() { return s_metrics; }

private:
    static SystemMetrics s_metrics;
};

/*
 * ========================================================================
 * BATCH UPDATE MANAGER
 * ========================================================================
 */

/*
 * BatchUpdateManager - Coordinates system updates
 *
 * Manages update frequency and ordering for all systems.
 * Supports different update rates for different systems.
 */
class BatchUpdateManager
{
public:
    static BatchUpdateManager& Instance()
    {
        static BatchUpdateManager instance;
        return instance;
    }

    /*
     * Configure update intervals (in milliseconds)
     */
    struct Config
    {
        uint32_t positionSyncInterval = 100;    // 10 Hz
        uint32_t vitalsSyncInterval = 200;      // 5 Hz
        uint32_t combatSyncInterval = 100;      // 10 Hz
        uint32_t aiUpdateInterval = 250;        // 4 Hz
        uint32_t spatialRebuildInterval = 1000; // 1 Hz
        uint32_t metricsUpdateInterval = 5000;  // 0.2 Hz
    };

    void SetConfig(const Config& config) { m_config = config; }
    const Config& GetConfig() const { return m_config; }

    /*
     * Main update entry point
     * Called each world update tick
     */
    void Update(uint32_t diff);

    /*
     * Get last update timing info
     */
    struct UpdateTiming
    {
        float totalMs = 0.0f;
        float syncMs = 0.0f;
        float movementMs = 0.0f;
        float combatMs = 0.0f;
        float aiMs = 0.0f;
        uint32_t botsUpdated = 0;
    };

    const UpdateTiming& GetLastTiming() const { return m_lastTiming; }

    /*
     * Get all system metrics
     */
    std::vector<const SystemMetrics*> GetAllMetrics() const;

private:
    BatchUpdateManager() = default;

    Config m_config;
    UpdateTiming m_lastTiming;

    // Last update timestamps
    uint32_t m_lastPositionSync = 0;
    uint32_t m_lastVitalsSync = 0;
    uint32_t m_lastCombatSync = 0;
    uint32_t m_lastAIUpdate = 0;
    uint32_t m_lastSpatialRebuild = 0;
    uint32_t m_lastMetricsUpdate = 0;
};

#define sBatchUpdateManager ecs::BatchUpdateManager::Instance()

} // namespace ecs

#endif // _PLAYERBOT_ECS_SYSTEMS_H
