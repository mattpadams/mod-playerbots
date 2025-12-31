/*
 * Squad AI - Hierarchical Group AI for Playerbots
 *
 * Implements a hierarchical command structure for coordinated bot behavior:
 *
 * Hierarchy:
 * - Commander (1): Raid leader, makes strategic decisions
 * - Squad Leaders (5-8): Group leaders, coordinate tactics
 * - Squad Members (5): Execute orders from squad leader
 *
 * Each level can issue orders to lower levels and reports status upward.
 */

#ifndef _PLAYERBOT_ECS_SQUAD_AI_H
#define _PLAYERBOT_ECS_SQUAD_AI_H

#include "Types.h"
#include <vector>
#include <unordered_map>
#include <functional>
#include <cstdint>

class Player;

namespace ecs {

/*
 * Squad roles for tactical assignment
 */
enum class SquadRole : uint8_t
{
    None = 0,
    Tank,           // Front-line defense
    Healer,         // Keep group alive
    MeleeDPS,       // Close-range damage
    RangedDPS,      // Long-range damage
    Support,        // Buffs, CC, utility
    Scout,          // Recon, pulling
    Reserve         // Backup, replacement
};

/*
 * Squad formation types
 */
enum class Formation : uint8_t
{
    None = 0,
    Tight,          // Close together for AoE heals
    Spread,         // Spread out to avoid cleaves
    Line,           // Single file for corridors
    Arc,            // Semi-circle around target
    Defensive,      // Tanks front, healers back
    Offensive,      // DPS front, tanks guard healers
    Custom
};

/*
 * Squad order types
 */
enum class OrderType : uint8_t
{
    None = 0,
    Move,           // Move to location
    Attack,         // Attack target
    Defend,         // Defend position/unit
    Assist,         // Assist squad member
    Follow,         // Follow leader
    Hold,           // Hold position
    Retreat,        // Fall back
    Spread,         // Spread out
    Stack,          // Stack on point
    Focus,          // Focus fire target
    CC,             // Crowd control target
    Interrupt,      // Interrupt target
    Heal,           // Priority heal target
    Custom
};

/*
 * Squad order structure
 */
struct SquadOrder
{
    OrderType type = OrderType::None;
    uint64_t targetGuid = 0;
    float x = 0, y = 0, z = 0;
    uint32_t mapId = 0;
    uint32_t spellId = 0;
    uint8_t priority = 0;
    uint64_t timestamp = 0;
    uint64_t expiresAt = 0;
};

/*
 * Squad member info
 */
struct SquadMemberInfo
{
    EntityId entityId = InvalidEntityId;
    uint64_t playerGuid = 0;
    SquadRole role = SquadRole::None;
    uint8_t classId = 0;
    uint8_t level = 0;
    uint16_t healthPct = 10000;
    uint16_t powerPct = 10000;
    uint8_t combatFlags = 0;
    float x = 0, y = 0, z = 0;
    uint64_t targetGuid = 0;
    uint32_t lastUpdateTime = 0;
};

/*
 * Squad - A group of bots working together
 */
class Squad
{
public:
    static constexpr size_t MAX_SQUAD_SIZE = 5;

    Squad(uint32_t id);

    // Member management
    bool AddMember(EntityId entity, SquadRole role);
    void RemoveMember(EntityId entity);
    bool HasMember(EntityId entity) const;
    size_t GetMemberCount() const { return m_members.size(); }
    const std::vector<SquadMemberInfo>& GetMembers() const { return m_members; }
    SquadMemberInfo* GetMember(EntityId entity);

    // Leadership
    void SetLeader(EntityId entity);
    EntityId GetLeader() const { return m_leader; }
    bool IsLeader(EntityId entity) const { return m_leader == entity; }

    // Orders
    void IssueOrder(const SquadOrder& order);
    const SquadOrder& GetCurrentOrder() const { return m_currentOrder; }
    void ClearOrder() { m_currentOrder = SquadOrder(); }

    // Formation
    void SetFormation(Formation formation) { m_formation = formation; }
    Formation GetFormation() const { return m_formation; }
    void GetFormationPosition(EntityId member, float leaderX, float leaderY, float& outX, float& outY) const;

    // Update
    void Update(uint32_t diff);
    void UpdateMemberInfo(EntityId entity, const SquadMemberInfo& info);

    // Status
    uint32_t GetId() const { return m_id; }
    float GetAverageHealthPct() const;
    bool IsInCombat() const;
    bool NeedsHealing() const;
    EntityId GetLowestHealthMember() const;
    EntityId GetHighestThreatTarget() const;

private:
    uint32_t m_id;
    EntityId m_leader = InvalidEntityId;
    std::vector<SquadMemberInfo> m_members;
    SquadOrder m_currentOrder;
    Formation m_formation = Formation::Defensive;
    uint64_t m_parentSquad = 0;  // For hierarchy
};

/*
 * SquadManager - Manages all squads
 */
class SquadManager
{
public:
    static SquadManager& Instance()
    {
        static SquadManager instance;
        return instance;
    }

    // Squad lifecycle
    Squad* CreateSquad();
    void DestroySquad(uint32_t squadId);
    Squad* GetSquad(uint32_t squadId);

    // Member assignment
    bool AssignToSquad(EntityId entity, uint32_t squadId, SquadRole role);
    void RemoveFromSquad(EntityId entity);
    Squad* GetSquadForEntity(EntityId entity);
    uint32_t GetSquadIdForEntity(EntityId entity);

    // Auto-squad formation
    void AutoFormSquads(const std::vector<EntityId>& entities);
    void BalanceSquads();

    // Update
    void Update(uint32_t diff);

    // Hierarchy
    void SetCommander(EntityId entity) { m_commander = entity; }
    EntityId GetCommander() const { return m_commander; }

    // Orders
    void BroadcastOrder(const SquadOrder& order);
    void IssueOrderToSquad(uint32_t squadId, const SquadOrder& order);

    // Status
    size_t GetSquadCount() const { return m_squads.size(); }
    size_t GetTotalMemberCount() const;

    // AI callback registration
    using SquadAICallback = std::function<void(Squad& squad, uint32_t diff)>;
    void RegisterSquadAI(SquadAICallback callback) { m_squadAICallbacks.push_back(callback); }

private:
    SquadManager() = default;

    SquadRole DetermineRoleForClass(uint8_t classId);
    void RunSquadAI(Squad& squad, uint32_t diff);

    std::unordered_map<uint32_t, Squad> m_squads;
    std::unordered_map<EntityId, uint32_t> m_entityToSquad;
    EntityId m_commander = InvalidEntityId;
    uint32_t m_nextSquadId = 1;

    std::vector<SquadAICallback> m_squadAICallbacks;
};

#define sSquadManager ecs::SquadManager::Instance()

/*
 * Default Squad AI behaviors
 */
namespace SquadAI {

// Register default behaviors
void RegisterDefaultBehaviors();

// Combat AI
void CombatBehavior(Squad& squad, uint32_t diff);

// Healing AI
void HealingBehavior(Squad& squad, uint32_t diff);

// Movement AI
void MovementBehavior(Squad& squad, uint32_t diff);

// Formation AI
void FormationBehavior(Squad& squad, uint32_t diff);

} // namespace SquadAI

} // namespace ecs

#endif // _PLAYERBOT_ECS_SQUAD_AI_H
