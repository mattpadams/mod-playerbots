/*
 * ECS Trigger Helpers - Fast cached checks for trigger evaluation
 *
 * This header provides optimized helper functions for common trigger checks.
 * Instead of expensive AI_VALUE calls that recalculate each time, these
 * helpers use the ECS value cache for O(1) lookups.
 *
 * Usage:
 * Replace: AI_VALUE(uint8, "attacker count")
 * With:    ecs::TriggerHelpers::GetAttackerCount(botAI)
 *
 * Replace: AI_VALUE(GuidVector, "attackers")
 * With:    ecs::TriggerHelpers::GetAttackers(botAI)
 */

#ifndef _PLAYERBOT_ECS_TRIGGERHELPERS_H
#define _PLAYERBOT_ECS_TRIGGERHELPERS_H

#include <vector>
#include <cstdint>

class PlayerbotAI;
class Player;
class Unit;

namespace ecs {

/*
 * TriggerHelpers - Static helper functions for fast trigger evaluation
 *
 * These functions check the ECS cache first, falling back to traditional
 * calculations if the cache is not available or stale.
 */
class TriggerHelpers
{
public:
    // =========================================================================
    // ATTACKER CHECKS
    // =========================================================================

    /*
     * Get count of attackers (entities with threat on bot or group)
     * Much faster than AI_VALUE(uint8, "attacker count")
     */
    static uint32_t GetAttackerCount(PlayerbotAI* botAI);

    /*
     * Get count of attackers specifically targeting this bot
     * Replaces AI_VALUE(uint8, "my attacker count")
     */
    static uint32_t GetMyAttackerCount(PlayerbotAI* botAI);

    /*
     * Check if bot has any attackers
     * Replaces AI_VALUE(uint8, "attacker count") > 0
     */
    static bool HasAttackers(PlayerbotAI* botAI);

    /*
     * Check if bot is being directly attacked
     * Replaces AI_VALUE(uint8, "my attacker count") > 0
     */
    static bool IsBeingAttacked(PlayerbotAI* botAI);

    /*
     * Get list of attacker GUIDs
     * Replaces AI_VALUE(GuidVector, "attackers")
     */
    static std::vector<uint64_t> GetAttackers(PlayerbotAI* botAI);

    // =========================================================================
    // TARGET CHECKS
    // =========================================================================

    /*
     * Get count of possible targets in range
     * Replaces AI_VALUE(GuidVector, "possible targets").size()
     */
    static uint32_t GetPossibleTargetCount(PlayerbotAI* botAI, float range = 0.0f);

    /*
     * Check if there are any possible targets
     * Replaces !AI_VALUE(GuidVector, "possible targets").empty()
     */
    static bool HasPossibleTargets(PlayerbotAI* botAI, float range = 0.0f);

    /*
     * Get list of possible target GUIDs
     * Replaces AI_VALUE(GuidVector, "possible targets")
     */
    static std::vector<uint64_t> GetPossibleTargets(PlayerbotAI* botAI, float range = 0.0f);

    // =========================================================================
    // HEALTH/POWER CHECKS
    // =========================================================================

    /*
     * Get bot's health percentage (0-100)
     * Replaces AI_VALUE2(uint8, "health", "self target")
     */
    static float GetHealthPercent(PlayerbotAI* botAI);

    /*
     * Get bot's mana/power percentage (0-100)
     * Replaces AI_VALUE2(uint8, "mana", "self target")
     */
    static float GetPowerPercent(PlayerbotAI* botAI);

    /*
     * Check if health is below threshold
     * Replaces AI_VALUE2(uint8, "health", "self target") < threshold
     */
    static bool IsHealthBelow(PlayerbotAI* botAI, float threshold);

    /*
     * Check if mana/power is below threshold
     * Replaces AI_VALUE2(uint8, "mana", "self target") < threshold
     */
    static bool IsPowerBelow(PlayerbotAI* botAI, float threshold);

    /*
     * Check if bot is in critical health (<15%)
     */
    static bool IsCriticalHealth(PlayerbotAI* botAI);

    /*
     * Check if bot is in low health (<30%)
     */
    static bool IsLowHealth(PlayerbotAI* botAI);

    // =========================================================================
    // COMBAT STATE CHECKS
    // =========================================================================

    /*
     * Check if bot is in combat
     * Replaces AI_VALUE2(bool, "combat", "self target")
     */
    static bool IsInCombat(PlayerbotAI* botAI);

    /*
     * Check if bot is casting a spell
     */
    static bool IsCasting(PlayerbotAI* botAI);

    /*
     * Check if bot is moving
     */
    static bool IsMoving(PlayerbotAI* botAI);

    // =========================================================================
    // AOE CHECKS
    // =========================================================================

    /*
     * Count attackers within range of a point
     * Useful for AoE trigger decisions
     */
    static uint32_t CountAttackersInRange(PlayerbotAI* botAI, float x, float y, float z, float range);

    /*
     * Count attackers within range of current target
     * Replaces the AoeTrigger calculation
     */
    static uint32_t CountAttackersNearTarget(PlayerbotAI* botAI, float range = 8.0f);

    // =========================================================================
    // PARTY/GROUP CHECKS
    // =========================================================================

    /*
     * Get count of party/raid members
     */
    static uint32_t GetPartyMemberCount(PlayerbotAI* botAI);

    /*
     * Check if any party member needs healing (health < 90%)
     */
    static bool AnyPartyMemberNeedsHealing(PlayerbotAI* botAI);

    /*
     * Count party members with health below threshold
     */
    static uint32_t CountPartyMembersBelowHealth(PlayerbotAI* botAI, float threshold);
};

/*
 * =========================================================================
 * MACRO REPLACEMENTS
 * =========================================================================
 *
 * These macros can be used to gradually replace AI_VALUE calls with cached
 * versions. They check if ECS is available and fall back to traditional
 * method if not.
 *
 * Usage:
 *   // Before:
 *   bool hasAttackers = AI_VALUE(uint8, "attacker count") > 0;
 *
 *   // After:
 *   bool hasAttackers = ECS_HAS_ATTACKERS(botAI);
 */

#define ECS_ATTACKER_COUNT(botAI) ecs::TriggerHelpers::GetAttackerCount(botAI)
#define ECS_MY_ATTACKER_COUNT(botAI) ecs::TriggerHelpers::GetMyAttackerCount(botAI)
#define ECS_HAS_ATTACKERS(botAI) ecs::TriggerHelpers::HasAttackers(botAI)
#define ECS_IS_BEING_ATTACKED(botAI) ecs::TriggerHelpers::IsBeingAttacked(botAI)

#define ECS_POSSIBLE_TARGET_COUNT(botAI) ecs::TriggerHelpers::GetPossibleTargetCount(botAI)
#define ECS_HAS_POSSIBLE_TARGETS(botAI) ecs::TriggerHelpers::HasPossibleTargets(botAI)

#define ECS_HEALTH_PCT(botAI) ecs::TriggerHelpers::GetHealthPercent(botAI)
#define ECS_POWER_PCT(botAI) ecs::TriggerHelpers::GetPowerPercent(botAI)
#define ECS_IS_LOW_HEALTH(botAI) ecs::TriggerHelpers::IsLowHealth(botAI)
#define ECS_IS_CRITICAL_HEALTH(botAI) ecs::TriggerHelpers::IsCriticalHealth(botAI)

#define ECS_IS_IN_COMBAT(botAI) ecs::TriggerHelpers::IsInCombat(botAI)

#define ECS_AOE_COUNT(botAI, range) ecs::TriggerHelpers::CountAttackersNearTarget(botAI, range)

} // namespace ecs

#endif // _PLAYERBOT_ECS_TRIGGERHELPERS_H
