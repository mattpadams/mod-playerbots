/*
 * ECS Value Cache - Fast cached value lookups for bot AI
 *
 * This system replaces expensive per-bot calculations with shared
 * ECS-based caches. Key optimizations:
 *
 * 1. Spatial queries are done once per map, shared across all bots
 * 2. Target lists are cached and invalidated on events
 * 3. Common calculations (health%, distance) use ECS components
 *
 * Performance target: 10x reduction in Value calculation time
 */

#ifndef _PLAYERBOT_ECS_VALUECACHE_H
#define _PLAYERBOT_ECS_VALUECACHE_H

#include "Types.h"
#include "Registry.h"
#include "Components.h"
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <cmath>

class Player;
class Unit;
class PlayerbotAI;

namespace ecs {

// Forward declarations
class BotRegistry;

/*
 * ========================================================================
 * SPATIAL INDEX - Per-map unit tracking for fast neighbor queries
 * ========================================================================
 */

/*
 * SpatialCell - Units within a spatial partition cell
 */
struct SpatialCell
{
    std::vector<uint64_t> unitGuids;    // All unit GUIDs in this cell
    std::vector<uint64_t> hostileGuids; // Pre-filtered hostile units
    std::vector<uint64_t> friendlyGuids;// Pre-filtered friendly units
    uint32_t lastUpdate = 0;
};

/*
 * MapSpatialIndex - Spatial index for a single map
 *
 * Uses a grid-based spatial hash for O(1) cell lookup.
 * Cell size is tuned for typical engagement ranges (32 yards).
 */
class MapSpatialIndex
{
public:
    static constexpr float CELL_SIZE = 32.0f;
    static constexpr int32_t CELL_OFFSET = 1000;  // Offset to handle negative coords

    MapSpatialIndex(uint32_t mapId) : m_mapId(mapId) {}

    // Update unit position in the index
    void UpdateUnit(uint64_t guid, float x, float y, bool isHostile, bool isFriendly);

    // Remove unit from index
    void RemoveUnit(uint64_t guid);

    // Find all units within radius of position
    std::vector<uint64_t> FindUnitsInRange(float x, float y, float radius) const;

    // Find hostile units within radius
    std::vector<uint64_t> FindHostilesInRange(float x, float y, float radius) const;

    // Find friendly units within radius
    std::vector<uint64_t> FindFriendliesInRange(float x, float y, float radius) const;

    // Clear all data
    void Clear();

    // Get statistics
    size_t GetUnitCount() const { return m_unitCells.size(); }
    size_t GetCellCount() const { return m_cells.size(); }

private:
    static int64_t CellKey(int32_t cellX, int32_t cellY)
    {
        return (static_cast<int64_t>(cellX + CELL_OFFSET) << 32) |
               static_cast<int64_t>(cellY + CELL_OFFSET);
    }

    static int32_t ToCellCoord(float worldCoord)
    {
        return static_cast<int32_t>(std::floor(worldCoord / CELL_SIZE));
    }

    uint32_t m_mapId;
    std::unordered_map<int64_t, SpatialCell> m_cells;
    std::unordered_map<uint64_t, int64_t> m_unitCells;  // guid -> current cell key
};

/*
 * WorldSpatialIndex - Manages spatial indices for all maps
 */
class WorldSpatialIndex
{
public:
    static WorldSpatialIndex& Instance()
    {
        static WorldSpatialIndex instance;
        return instance;
    }

    // Get or create index for a map
    MapSpatialIndex& GetMapIndex(uint32_t mapId);

    // Update a unit's position
    void UpdateUnit(uint32_t mapId, uint64_t guid, float x, float y, bool isHostile, bool isFriendly);

    // Remove a unit
    void RemoveUnit(uint32_t mapId, uint64_t guid);

    // Clear all indices
    void Clear();

private:
    WorldSpatialIndex() = default;
    std::unordered_map<uint32_t, MapSpatialIndex> m_mapIndices;
};

#define sWorldSpatialIndex ecs::WorldSpatialIndex::Instance()

/*
 * ========================================================================
 * TARGET CACHE - Cached lists of valid targets
 * ========================================================================
 */

/*
 * CachedTargetList - A cached list of target GUIDs with validity info
 */
struct CachedTargetList
{
    std::vector<uint64_t> guids;
    uint32_t lastUpdate = 0;
    uint32_t validUntil = 0;
    bool valid = false;

    bool IsValid(uint32_t now) const { return valid && now < validUntil; }
    void Invalidate() { valid = false; }
    void Update(const std::vector<uint64_t>& newGuids, uint32_t now, uint32_t ttlMs)
    {
        guids = newGuids;
        lastUpdate = now;
        validUntil = now + ttlMs;
        valid = true;
    }
};

/*
 * BotTargetCache - Per-bot cache of target lists
 *
 * Caches:
 * - Attackers (units attacking this bot or group)
 * - Possible targets (hostile units in range)
 * - Friendly targets (for healing)
 */
struct BotTargetCache
{
    EntityId entity;
    uint64_t playerGuid = 0;

    CachedTargetList attackers;           // Units with threat on bot/group
    CachedTargetList possibleTargets;     // All hostile units in sight range
    CachedTargetList friendlyTargets;     // Party/raid members in range
    CachedTargetList healTargets;         // Units that need healing

    // Timestamps for rate limiting
    uint32_t lastAttackerUpdate = 0;
    uint32_t lastPossibleTargetUpdate = 0;
    uint32_t lastFriendlyUpdate = 0;

    // Cache validity (ms)
    static constexpr uint32_t ATTACKER_TTL = 500;      // 0.5 seconds
    static constexpr uint32_t POSSIBLE_TARGET_TTL = 1000;  // 1 second
    static constexpr uint32_t FRIENDLY_TTL = 2000;     // 2 seconds

    void InvalidateAll()
    {
        attackers.Invalidate();
        possibleTargets.Invalidate();
        friendlyTargets.Invalidate();
        healTargets.Invalidate();
    }
};

/*
 * TargetCacheManager - Manages target caches for all bots
 */
class TargetCacheManager
{
public:
    static TargetCacheManager& Instance()
    {
        static TargetCacheManager instance;
        return instance;
    }

    // Get or create cache for a bot
    BotTargetCache& GetCache(EntityId entity);
    BotTargetCache& GetCacheByGuid(uint64_t playerGuid);

    // Remove cache when bot is unregistered
    void RemoveCache(EntityId entity);
    void RemoveCacheByGuid(uint64_t playerGuid);

    // Invalidate caches for bots near an event
    void InvalidateNearby(uint32_t mapId, float x, float y, float radius);

    // Invalidate all caches (on major events)
    void InvalidateAll();

    // Get attackers for a bot (uses cache or recalculates)
    std::vector<uint64_t> GetAttackers(PlayerbotAI* botAI, Player* player, uint32_t now);

    // Get possible targets for a bot
    std::vector<uint64_t> GetPossibleTargets(PlayerbotAI* botAI, Player* player, uint32_t now, float range);

    // Get friendly targets for a bot
    std::vector<uint64_t> GetFriendlyTargets(PlayerbotAI* botAI, Player* player, uint32_t now, float range);

    // Statistics
    size_t GetCacheCount() const { return m_caches.size(); }
    uint32_t GetCacheHits() const { return m_cacheHits; }
    uint32_t GetCacheMisses() const { return m_cacheMisses; }
    float GetHitRate() const
    {
        uint32_t total = m_cacheHits + m_cacheMisses;
        return total > 0 ? (100.0f * m_cacheHits / total) : 0.0f;
    }
    void ResetStats() { m_cacheHits = 0; m_cacheMisses = 0; }

private:
    TargetCacheManager() = default;

    // Internal calculation methods
    std::vector<uint64_t> CalculateAttackers(PlayerbotAI* botAI, Player* player);
    std::vector<uint64_t> CalculatePossibleTargets(Player* player, float range);
    std::vector<uint64_t> CalculateFriendlyTargets(Player* player, float range);

    std::unordered_map<uint32_t, BotTargetCache> m_caches;  // entityId.Raw() -> cache
    std::unordered_map<uint64_t, EntityId> m_guidToEntity;  // playerGuid -> entityId

    // Statistics
    uint32_t m_cacheHits = 0;
    uint32_t m_cacheMisses = 0;
};

#define sTargetCacheManager ecs::TargetCacheManager::Instance()

/*
 * ========================================================================
 * VALUE CACHE COMPONENT - Per-bot cached values
 * ========================================================================
 */

/*
 * ValueCache - Component storing cached calculated values for a bot
 *
 * This component can be added to bot entities to cache frequently
 * accessed values that are expensive to calculate.
 */
struct ValueCache
{
    // Health state (synced from ECS Health component)
    float healthPercent = 100.0f;
    float powerPercent = 100.0f;
    bool isLowHealth = false;
    bool isLowPower = false;

    // Combat state
    uint32_t attackerCount = 0;
    uint32_t possibleTargetCount = 0;
    bool hasAttackers = false;
    bool hasPossibleTargets = false;

    // Target info
    float targetDistance = 0.0f;
    bool targetInRange = false;
    bool targetInLoS = false;

    // Party info
    uint32_t partySize = 0;
    uint32_t healTargetCount = 0;
    bool anyPartyMemberLowHealth = false;

    // Timestamps
    uint32_t lastUpdate = 0;
    uint32_t lastCombatInfoUpdate = 0;
    uint32_t lastPartyInfoUpdate = 0;

    // Update intervals
    static constexpr uint32_t UPDATE_INTERVAL = 100;         // 10 Hz
    static constexpr uint32_t COMBAT_UPDATE_INTERVAL = 200;  // 5 Hz
    static constexpr uint32_t PARTY_UPDATE_INTERVAL = 500;   // 2 Hz
};

/*
 * ========================================================================
 * VALUE CACHE SYSTEM - Update cached values
 * ========================================================================
 */

/*
 * ValueCacheSystem - Updates ValueCache components from ECS state
 */
class ValueCacheSystem
{
public:
    // Update all value caches
    static void Update(Registry& registry, uint32_t now);

    // Update a single bot's cache
    static void UpdateBot(EntityId entity, Registry& registry, uint32_t now);

    // Get metrics
    struct Metrics
    {
        uint32_t botsUpdated = 0;
        float updateTimeMs = 0.0f;
        float avgUpdateTimeMs = 0.0f;
    };

    static const Metrics& GetMetrics() { return s_metrics; }

private:
    static Metrics s_metrics;
};

/*
 * ========================================================================
 * INTEGRATION HELPERS - Bridge to existing Value system
 * ========================================================================
 */

/*
 * ECS-backed value getters for use by existing code
 *
 * These provide fast access to cached values, falling back to
 * calculation if the cache is stale.
 */
namespace CachedValues
{
    // Get attackers using cache (returns GUIDs)
    std::vector<uint64_t> GetAttackers(PlayerbotAI* botAI);

    // Get possible targets using cache
    std::vector<uint64_t> GetPossibleTargets(PlayerbotAI* botAI, float range = 0.0f);

    // Get friendly targets using cache
    std::vector<uint64_t> GetFriendlyTargets(PlayerbotAI* botAI, float range = 0.0f);

    // Fast health/power checks (uses ECS components)
    float GetHealthPercent(PlayerbotAI* botAI);
    float GetPowerPercent(PlayerbotAI* botAI);
    bool IsLowHealth(PlayerbotAI* botAI, float threshold = 30.0f);
    bool IsLowPower(PlayerbotAI* botAI, float threshold = 20.0f);

    // Fast combat state checks
    bool IsInCombat(PlayerbotAI* botAI);
    bool HasAttackers(PlayerbotAI* botAI);
    uint32_t GetAttackerCount(PlayerbotAI* botAI);

    // Fast distance calculation (uses cached position)
    float GetDistanceToTarget(PlayerbotAI* botAI, Unit* target);
    float GetDistanceToTarget(PlayerbotAI* botAI, uint64_t targetGuid);

    // Register a bot for value caching
    void RegisterBot(PlayerbotAI* botAI, Player* player);

    // Unregister a bot
    void UnregisterBot(uint64_t playerGuid);
}

} // namespace ecs

#endif // _PLAYERBOT_ECS_VALUECACHE_H
