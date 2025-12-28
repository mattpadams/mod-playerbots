/*
 * ECS Hot/Cold Data Separation
 *
 * Separates frequently accessed (hot) data from rarely accessed (cold) data
 * to improve cache efficiency during batch processing.
 *
 * Hot data (accessed every tick):
 * - Position (x, y, z, mapId)
 * - Health/Power current values
 * - Combat state flags
 * - AI state
 *
 * Cold data (accessed occasionally):
 * - Player name, guild info
 * - Equipment stats
 * - Talent specs
 * - Full buff lists
 */

#ifndef _PLAYERBOT_ECS_HOT_COLD_DATA_H
#define _PLAYERBOT_ECS_HOT_COLD_DATA_H

#include "Types.h"
#include <cstdint>

namespace ecs {

/*
 * HotData - Frequently accessed per-tick data (~64 bytes target)
 *
 * Designed to fit in a single cache line for optimal performance.
 * All data needed for typical per-tick decisions.
 */
struct HotData
{
    // Position (16 bytes)
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float orientation = 0.0f;

    // Vitals (8 bytes)
    uint32_t health = 0;
    uint32_t power = 0;

    // State flags (4 bytes packed)
    uint8_t aiState = 0;          // AIState::State
    uint8_t combatFlags = 0;      // Packed: inCombat, isCasting, isMoving, etc.
    uint8_t roleFlags = 0;        // Packed: role, isLeader, etc.
    uint8_t updateFlags = 0;      // Packed: needsSync, dirty, etc.

    // Identifiers (16 bytes)
    uint32_t mapId = 0;
    uint32_t targetGuidLow = 0;   // Low part of target GUID
    uint32_t lastUpdateTime = 0;
    uint32_t nextUpdateTime = 0;

    // Quick stats (8 bytes)
    uint16_t healthPct = 100;     // 0-100 as fixed point (x100 for precision)
    uint16_t powerPct = 100;
    uint16_t level = 1;
    uint8_t classId = 0;
    uint8_t raceId = 0;

    // Computed spatial (8 bytes)
    int16_t cellX = 0;
    int16_t cellY = 0;
    uint16_t zoneId = 0;
    uint16_t areaId = 0;

    // Total: 60 bytes (fits in 64-byte cache line with padding)

    // Combat flag accessors
    bool IsInCombat() const { return combatFlags & 0x01; }
    bool IsCasting() const { return combatFlags & 0x02; }
    bool IsMoving() const { return combatFlags & 0x04; }
    bool IsChanneling() const { return combatFlags & 0x08; }
    bool IsDead() const { return combatFlags & 0x10; }
    bool IsStunned() const { return combatFlags & 0x20; }
    bool IsFeared() const { return combatFlags & 0x40; }
    bool IsRooted() const { return combatFlags & 0x80; }

    void SetInCombat(bool v) { if (v) combatFlags |= 0x01; else combatFlags &= ~0x01; }
    void SetCasting(bool v) { if (v) combatFlags |= 0x02; else combatFlags &= ~0x02; }
    void SetMoving(bool v) { if (v) combatFlags |= 0x04; else combatFlags &= ~0x04; }
    void SetChanneling(bool v) { if (v) combatFlags |= 0x08; else combatFlags &= ~0x08; }
    void SetDead(bool v) { if (v) combatFlags |= 0x10; else combatFlags &= ~0x10; }
    void SetStunned(bool v) { if (v) combatFlags |= 0x20; else combatFlags &= ~0x20; }
    void SetFeared(bool v) { if (v) combatFlags |= 0x40; else combatFlags &= ~0x40; }
    void SetRooted(bool v) { if (v) combatFlags |= 0x80; else combatFlags &= ~0x80; }

    // Update flag accessors
    bool NeedsSync() const { return updateFlags & 0x01; }
    bool IsDirty() const { return updateFlags & 0x02; }
    void SetNeedsSync(bool v) { if (v) updateFlags |= 0x01; else updateFlags &= ~0x01; }
    void SetDirty(bool v) { if (v) updateFlags |= 0x02; else updateFlags &= ~0x02; }
};

static_assert(sizeof(HotData) <= 64, "HotData should fit in a cache line");

/*
 * ColdData - Rarely accessed data
 *
 * Stored separately to avoid polluting cache during hot path processing.
 */
struct ColdData
{
    // Extended identifiers
    uint64_t playerGuid = 0;
    uint64_t masterGuid = 0;
    uint32_t accountId = 0;

    // Stats
    uint32_t maxHealth = 0;
    uint32_t maxPower = 0;
    uint32_t attackPower = 0;
    uint32_t spellPower = 0;
    uint32_t armor = 0;
    float critChance = 0.0f;

    // Talent/spec info
    uint8_t talentSpec = 0;
    uint8_t primaryRole = 0;
    uint8_t secondaryRole = 0;

    // State timing
    uint32_t combatStartTime = 0;
    uint32_t lastCombatTime = 0;
    uint32_t lastMoveTime = 0;
    uint32_t stateStartTime = 0;

    // Group info
    uint64_t groupGuid = 0;
    uint8_t groupRole = 0;
    uint8_t raidSubgroup = 0;

    // Padding to reasonable size
    uint8_t reserved[32] = {};
};

} // namespace ecs

// Forward declaration at global scope
class Player;

namespace ecs {

/*
 * HotDataSync - Utilities for syncing hot data from game objects
 */
class HotDataSync
{
public:
    // Sync hot data from a Player object
    static void SyncFromPlayer(::Player* player, HotData& hot);

    // Sync cold data from a Player object
    static void SyncColdFromPlayer(::Player* player, ColdData& cold);

    // Pack combat state into flags
    static uint8_t PackCombatFlags(::Player* player);
};

} // namespace ecs

#endif // _PLAYERBOT_ECS_HOT_COLD_DATA_H
