/*
 * ECS Components - Core data structures for bot state
 *
 * Components are plain data structs (POD-like) that store entity state.
 * Each component should:
 * - Be trivially copyable for cache efficiency
 * - Contain only data, no behavior
 * - Be small and focused (single responsibility)
 *
 * Components are stored contiguously by type for cache-friendly iteration.
 */

#ifndef _PLAYERBOT_ECS_COMPONENTS_H
#define _PLAYERBOT_ECS_COMPONENTS_H

#include "Types.h"
#include <cstdint>
#include <array>

// Forward declarations to avoid heavy includes
class PlayerbotAI;
class Player;
class Unit;

namespace ecs {

/*
 * ========================================================================
 * SPATIAL COMPONENTS - Position and movement
 * ========================================================================
 */

/*
 * Position - World location of an entity
 *
 * Frequently accessed for:
 * - Spatial queries (find nearby targets)
 * - Movement updates
 * - Range checks
 */
struct Position
{
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float orientation = 0.0f;
    uint32_t mapId = 0;
    uint32_t zoneId = 0;
    uint32_t areaId = 0;

    // Spatial partitioning cell (computed, not stored in DB)
    int32_t cellX = 0;
    int32_t cellY = 0;
};

/*
 * Velocity - Movement state
 */
struct Velocity
{
    float dx = 0.0f;
    float dy = 0.0f;
    float dz = 0.0f;
    float speed = 0.0f;           // Current movement speed
    bool isMoving = false;
    bool isFalling = false;
};

/*
 * PathState - Navigation/pathfinding state
 */
struct PathState
{
    float targetX = 0.0f;
    float targetY = 0.0f;
    float targetZ = 0.0f;
    uint32_t pathId = 0;          // Current path being followed
    uint8_t waypointIndex = 0;    // Current waypoint in path
    bool hasPath = false;
    bool pathComplete = false;
};

/*
 * ========================================================================
 * VITAL COMPONENTS - Health, resources
 * ========================================================================
 */

/*
 * Health - Health and death state
 */
struct Health
{
    uint32_t current = 0;
    uint32_t max = 0;
    bool isDead = false;
    bool isGhost = false;

    [[nodiscard]] float Percent() const { return max > 0 ? (100.0f * current / max) : 0.0f; }
    [[nodiscard]] bool IsLow() const { return Percent() < 30.0f; }
    [[nodiscard]] bool IsCritical() const { return Percent() < 15.0f; }
};

/*
 * Power - Mana/Rage/Energy resources
 */
struct Power
{
    enum class Type : uint8_t
    {
        Mana = 0,
        Rage = 1,
        Energy = 3,
        Runic = 6
    };

    Type powerType = Type::Mana;
    uint32_t current = 0;
    uint32_t max = 0;

    [[nodiscard]] float Percent() const { return max > 0 ? (100.0f * current / max) : 0.0f; }
    [[nodiscard]] bool IsLow() const { return Percent() < 20.0f; }
};

/*
 * Stats - Core character stats (cached)
 */
struct Stats
{
    uint8_t level = 1;
    uint8_t classId = 0;
    uint8_t raceId = 0;
    uint8_t spec = 0;             // Talent specialization

    uint32_t attackPower = 0;
    uint32_t spellPower = 0;
    float critChance = 0.0f;
    float hitRating = 0.0f;
    uint32_t armor = 0;
};

/*
 * ========================================================================
 * COMBAT COMPONENTS - Targeting and combat state
 * ========================================================================
 */

/*
 * Target - Current combat target
 */
struct Target
{
    EntityId targetEntity;          // ECS entity (if tracked)
    uint64_t targetGuid = 0;        // WoW object GUID (for non-ECS targets)
    float distance = 0.0f;
    bool inRange = false;
    bool inLineOfSight = false;
    uint32_t lastLosCheck = 0;      // Timestamp of last LoS check
};

/*
 * ThreatList - Entities threatening this entity
 * Fixed-size for cache efficiency
 */
struct ThreatList
{
    static constexpr size_t MAX_THREATS = 8;

    struct ThreatEntry
    {
        EntityId entity;
        uint64_t guid = 0;
        float threat = 0.0f;
    };

    std::array<ThreatEntry, MAX_THREATS> threats;
    uint8_t count = 0;
    bool hasThreat = false;
};

/*
 * CombatState - Combat status flags
 */
struct CombatState
{
    bool inCombat = false;
    bool isAttacking = false;
    bool isCasting = false;
    bool isChanneling = false;
    bool isFleeing = false;
    bool isStunned = false;
    bool isFeared = false;
    bool isRooted = false;
    uint32_t castingSpellId = 0;
    uint32_t combatStartTime = 0;
};

/*
 * Cooldowns - Ability cooldown tracking
 * Uses bitfields for common abilities, map for others
 */
struct Cooldowns
{
    static constexpr size_t MAX_TRACKED = 32;

    // Timestamps when abilities come off cooldown
    std::array<uint32_t, MAX_TRACKED> cooldownEnds;
    uint32_t globalCooldownEnd = 0;

    [[nodiscard]] bool IsOnGCD() const;
    [[nodiscard]] bool IsReady(uint8_t slotIndex) const;
};

/*
 * ========================================================================
 * AI COMPONENTS - Bot behavior and decision-making
 * ========================================================================
 */

/*
 * AIState - High-level AI state machine
 */
struct AIState
{
    enum class State : uint8_t
    {
        Idle = 0,
        Combat,
        Following,
        Traveling,
        Looting,
        Trading,
        Resting,
        Dead
    };

    State currentState = State::Idle;
    State previousState = State::Idle;
    uint32_t stateStartTime = 0;
    uint32_t lastUpdateTime = 0;
    uint32_t nextUpdateTime = 0;    // When to run next AI tick
    uint16_t updateInterval = 100;  // ms between updates
};

/*
 * BotRole - Combat role assignment
 */
struct BotRole
{
    enum class Role : uint8_t
    {
        DPS = 0,
        Tank,
        Healer,
        Support
    };

    Role primaryRole = Role::DPS;
    Role secondaryRole = Role::DPS;
    bool isMainTank = false;
    bool isMainAssist = false;
    bool isOffTank = false;
};

/*
 * SquadMember - Hierarchical AI group membership
 */
struct SquadMember
{
    EntityId squadLeader;           // Leader entity (or Invalid if standalone)
    EntityId followTarget;          // Who to follow
    uint8_t squadPosition = 0;      // Position in formation
    float followDistance = 5.0f;
    float followAngle = 0.0f;
    bool isLeader = false;
};

/*
 * ========================================================================
 * ADAPTER COMPONENTS - Bridge to existing system
 * ========================================================================
 */

/*
 * BotLink - Links ECS entity to existing PlayerbotAI
 *
 * This is the key component for incremental migration.
 * Allows ECS to coexist with the current OOP architecture.
 */
struct BotLink
{
    PlayerbotAI* botAI = nullptr;   // Pointer to existing bot instance
    Player* player = nullptr;        // WoW Player object
    uint64_t playerGuid = 0;         // Player GUID for lookups

    // Sync flags - which components need syncing from WoW state
    bool needsPositionSync = true;
    bool needsHealthSync = true;
    bool needsCombatSync = true;
    uint32_t lastSyncTime = 0;
};

/*
 * Dirty - Marks components that have changed and need processing
 */
struct Dirty
{
    uint32_t flags = 0;

    static constexpr uint32_t POSITION = 1 << 0;
    static constexpr uint32_t HEALTH = 1 << 1;
    static constexpr uint32_t POWER = 1 << 2;
    static constexpr uint32_t COMBAT = 1 << 3;
    static constexpr uint32_t TARGET = 1 << 4;
    static constexpr uint32_t AI_STATE = 1 << 5;

    void Set(uint32_t flag) { flags |= flag; }
    void Clear(uint32_t flag) { flags &= ~flag; }
    [[nodiscard]] bool Has(uint32_t flag) const { return (flags & flag) != 0; }
    void Reset() { flags = 0; }
};

/*
 * ========================================================================
 * UTILITY COMPONENTS - Misc tracking
 * ========================================================================
 */

/*
 * Timers - General purpose timer tracking
 */
struct Timers
{
    uint32_t created = 0;           // When entity was created
    uint32_t lastActivity = 0;      // Last meaningful action
    uint32_t lastCombat = 0;        // Last combat activity
    uint32_t afkTime = 0;           // Time inactive
};

/*
 * DebugInfo - Development/debugging data (optional)
 */
struct DebugInfo
{
    static constexpr size_t NAME_LEN = 32;
    char name[NAME_LEN] = {0};
    uint32_t updateCount = 0;
    float avgUpdateTimeMs = 0.0f;
    uint32_t lastError = 0;
};

} // namespace ecs

#endif // _PLAYERBOT_ECS_COMPONENTS_H
