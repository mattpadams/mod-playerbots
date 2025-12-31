/*
 * Squad AI Implementation
 */

#include "SquadAI.h"
#include "Log.h"
#include <algorithm>
#include <cmath>

namespace ecs {

// =============================================================================
// Squad Implementation
// =============================================================================

Squad::Squad(uint32_t id) : m_id(id)
{
    m_members.reserve(MAX_SQUAD_SIZE);
}

bool Squad::AddMember(EntityId entity, SquadRole role)
{
    if (m_members.size() >= MAX_SQUAD_SIZE)
        return false;

    if (HasMember(entity))
        return false;

    SquadMemberInfo info;
    info.entityId = entity;
    info.role = role;
    m_members.push_back(info);

    // First member becomes leader
    if (m_members.size() == 1)
    {
        m_leader = entity;
    }

    return true;
}

void Squad::RemoveMember(EntityId entity)
{
    auto it = std::find_if(m_members.begin(), m_members.end(),
        [entity](const SquadMemberInfo& m) { return m.entityId == entity; });

    if (it != m_members.end())
    {
        m_members.erase(it);

        // Reassign leader if needed
        if (m_leader == entity && !m_members.empty())
        {
            // Prefer tank as leader, then healer, then anyone
            m_leader = m_members[0].entityId;
            for (const auto& member : m_members)
            {
                if (member.role == SquadRole::Tank)
                {
                    m_leader = member.entityId;
                    break;
                }
                else if (member.role == SquadRole::Healer && m_leader != member.entityId)
                {
                    m_leader = member.entityId;
                }
            }
        }
    }
}

bool Squad::HasMember(EntityId entity) const
{
    return std::find_if(m_members.begin(), m_members.end(),
        [entity](const SquadMemberInfo& m) { return m.entityId == entity; }) != m_members.end();
}

SquadMemberInfo* Squad::GetMember(EntityId entity)
{
    auto it = std::find_if(m_members.begin(), m_members.end(),
        [entity](const SquadMemberInfo& m) { return m.entityId == entity; });
    return it != m_members.end() ? &(*it) : nullptr;
}

void Squad::SetLeader(EntityId entity)
{
    if (HasMember(entity))
    {
        m_leader = entity;
    }
}

void Squad::IssueOrder(const SquadOrder& order)
{
    m_currentOrder = order;
}

void Squad::GetFormationPosition(EntityId member, float leaderX, float leaderY, float& outX, float& outY) const
{
    // Find member index
    size_t idx = 0;
    for (size_t i = 0; i < m_members.size(); ++i)
    {
        if (m_members[i].entityId == member)
        {
            idx = i;
            break;
        }
    }

    // Default spacing
    const float SPACING = 3.0f;

    switch (m_formation)
    {
        case Formation::Tight:
        {
            // Cluster around leader
            float angle = (2.0f * 3.14159f * idx) / m_members.size();
            outX = leaderX + SPACING * 0.5f * std::cos(angle);
            outY = leaderY + SPACING * 0.5f * std::sin(angle);
            break;
        }
        case Formation::Spread:
        {
            // Wide circle around leader
            float angle = (2.0f * 3.14159f * idx) / m_members.size();
            outX = leaderX + SPACING * 2.0f * std::cos(angle);
            outY = leaderY + SPACING * 2.0f * std::sin(angle);
            break;
        }
        case Formation::Line:
        {
            // Single file behind leader
            outX = leaderX - SPACING * (idx + 1);
            outY = leaderY;
            break;
        }
        case Formation::Arc:
        {
            // Semi-circle in front of leader
            float angle = 3.14159f * (0.25f + 0.5f * idx / (m_members.size() - 1));
            outX = leaderX + SPACING * std::cos(angle);
            outY = leaderY + SPACING * std::sin(angle);
            break;
        }
        case Formation::Defensive:
        {
            // Tanks front, healers back
            const auto& memberInfo = m_members[idx];
            if (memberInfo.role == SquadRole::Tank)
            {
                outX = leaderX + SPACING;
                outY = leaderY + SPACING * (idx % 2 ? 1 : -1);
            }
            else if (memberInfo.role == SquadRole::Healer)
            {
                outX = leaderX - SPACING * 2;
                outY = leaderY + SPACING * (idx % 2 ? 1 : -1);
            }
            else
            {
                outX = leaderX;
                outY = leaderY + SPACING * (idx % 2 ? 1 : -1) * ((idx / 2) + 1);
            }
            break;
        }
        default:
        {
            // Default circle
            float angle = (2.0f * 3.14159f * idx) / m_members.size();
            outX = leaderX + SPACING * std::cos(angle);
            outY = leaderY + SPACING * std::sin(angle);
            break;
        }
    }
}

void Squad::Update(uint32_t /*diff*/)
{
    // Check order expiration
    if (m_currentOrder.expiresAt > 0)
    {
        // Get current time and check expiration
        // For now, just clear expired orders during explicit checks
    }
}

void Squad::UpdateMemberInfo(EntityId entity, const SquadMemberInfo& info)
{
    auto* member = GetMember(entity);
    if (member)
    {
        member->healthPct = info.healthPct;
        member->powerPct = info.powerPct;
        member->combatFlags = info.combatFlags;
        member->x = info.x;
        member->y = info.y;
        member->z = info.z;
        member->targetGuid = info.targetGuid;
        member->lastUpdateTime = info.lastUpdateTime;
    }
}

float Squad::GetAverageHealthPct() const
{
    if (m_members.empty())
        return 0.0f;

    uint32_t total = 0;
    for (const auto& member : m_members)
    {
        total += member.healthPct;
    }
    return static_cast<float>(total) / (m_members.size() * 100);
}

bool Squad::IsInCombat() const
{
    for (const auto& member : m_members)
    {
        if (member.combatFlags & 0x01)
            return true;
    }
    return false;
}

bool Squad::NeedsHealing() const
{
    for (const auto& member : m_members)
    {
        if (member.healthPct < 7000)  // 70%
            return true;
    }
    return false;
}

EntityId Squad::GetLowestHealthMember() const
{
    EntityId lowest = InvalidEntityId;
    uint16_t lowestHealth = 10001;

    for (const auto& member : m_members)
    {
        if (member.healthPct < lowestHealth)
        {
            lowestHealth = member.healthPct;
            lowest = member.entityId;
        }
    }

    return lowest;
}

EntityId Squad::GetHighestThreatTarget() const
{
    // Find the most common target among squad members
    std::unordered_map<uint64_t, int> targetCounts;

    for (const auto& member : m_members)
    {
        if (member.targetGuid != 0)
        {
            targetCounts[member.targetGuid]++;
        }
    }

    uint64_t highestTarget = 0;
    int highestCount = 0;
    for (const auto& [target, count] : targetCounts)
    {
        if (count > highestCount)
        {
            highestCount = count;
            highestTarget = target;
        }
    }

    // Return as EntityId (this is a simplification - in practice we'd look up the entity)
    return static_cast<EntityId>(highestTarget & 0xFFFFFFFF);
}

// =============================================================================
// SquadManager Implementation
// =============================================================================

Squad* SquadManager::CreateSquad()
{
    uint32_t id = m_nextSquadId++;
    auto result = m_squads.emplace(id, Squad(id));
    return &result.first->second;
}

void SquadManager::DestroySquad(uint32_t squadId)
{
    auto it = m_squads.find(squadId);
    if (it != m_squads.end())
    {
        // Remove all member mappings
        for (const auto& member : it->second.GetMembers())
        {
            m_entityToSquad.erase(member.entityId);
        }
        m_squads.erase(it);
    }
}

Squad* SquadManager::GetSquad(uint32_t squadId)
{
    auto it = m_squads.find(squadId);
    return it != m_squads.end() ? &it->second : nullptr;
}

bool SquadManager::AssignToSquad(EntityId entity, uint32_t squadId, SquadRole role)
{
    // Remove from current squad if any
    RemoveFromSquad(entity);

    Squad* squad = GetSquad(squadId);
    if (!squad)
        return false;

    if (squad->AddMember(entity, role))
    {
        m_entityToSquad[entity] = squadId;
        return true;
    }
    return false;
}

void SquadManager::RemoveFromSquad(EntityId entity)
{
    auto it = m_entityToSquad.find(entity);
    if (it != m_entityToSquad.end())
    {
        Squad* squad = GetSquad(it->second);
        if (squad)
        {
            squad->RemoveMember(entity);
        }
        m_entityToSquad.erase(it);
    }
}

Squad* SquadManager::GetSquadForEntity(EntityId entity)
{
    auto it = m_entityToSquad.find(entity);
    if (it != m_entityToSquad.end())
    {
        return GetSquad(it->second);
    }
    return nullptr;
}

uint32_t SquadManager::GetSquadIdForEntity(EntityId entity)
{
    auto it = m_entityToSquad.find(entity);
    return it != m_entityToSquad.end() ? it->second : 0;
}

void SquadManager::AutoFormSquads(const std::vector<EntityId>& entities)
{
    if (entities.empty())
        return;

    // Group entities by role
    std::vector<EntityId> tanks, healers, dps;

    for (EntityId entity : entities)
    {
        // For now, we'd need to look up the class to determine role
        // This is a placeholder - in practice we'd query the registry
        dps.push_back(entity);  // Default to DPS
    }

    // Create squads of MAX_SQUAD_SIZE
    size_t totalMembers = entities.size();
    size_t numSquads = (totalMembers + Squad::MAX_SQUAD_SIZE - 1) / Squad::MAX_SQUAD_SIZE;

    for (size_t i = 0; i < numSquads; ++i)
    {
        Squad* squad = CreateSquad();
        if (!squad)
            continue;

        // Add members to this squad
        size_t start = i * Squad::MAX_SQUAD_SIZE;
        size_t end = std::min(start + Squad::MAX_SQUAD_SIZE, totalMembers);

        for (size_t j = start; j < end; ++j)
        {
            AssignToSquad(entities[j], squad->GetId(), SquadRole::MeleeDPS);
        }
    }

    LOG_INFO("playerbots", "SquadManager: Auto-formed {} squads from {} entities",
        numSquads, totalMembers);
}

void SquadManager::BalanceSquads()
{
    // Redistribute members to balance squad sizes
    // This is a simple implementation - could be more sophisticated

    std::vector<Squad*> activeSquads;
    for (auto& [id, squad] : m_squads)
    {
        if (squad.GetMemberCount() > 0)
        {
            activeSquads.push_back(&squad);
        }
    }

    if (activeSquads.size() < 2)
        return;

    // Sort by member count
    std::sort(activeSquads.begin(), activeSquads.end(),
        [](Squad* a, Squad* b) { return a->GetMemberCount() < b->GetMemberCount(); });

    // Balance: move members from largest to smallest
    while (activeSquads.back()->GetMemberCount() - activeSquads.front()->GetMemberCount() > 1)
    {
        Squad* largest = activeSquads.back();
        Squad* smallest = activeSquads.front();

        // Move last member from largest to smallest
        if (!largest->GetMembers().empty())
        {
            EntityId memberToMove = largest->GetMembers().back().entityId;
            SquadRole role = largest->GetMembers().back().role;

            largest->RemoveMember(memberToMove);
            smallest->AddMember(memberToMove, role);
            m_entityToSquad[memberToMove] = smallest->GetId();
        }

        // Re-sort
        std::sort(activeSquads.begin(), activeSquads.end(),
            [](Squad* a, Squad* b) { return a->GetMemberCount() < b->GetMemberCount(); });
    }
}

void SquadManager::Update(uint32_t diff)
{
    for (auto& [id, squad] : m_squads)
    {
        squad.Update(diff);

        // Run registered AI callbacks
        for (auto& callback : m_squadAICallbacks)
        {
            callback(squad, diff);
        }
    }
}

size_t SquadManager::GetTotalMemberCount() const
{
    size_t total = 0;
    for (const auto& [id, squad] : m_squads)
    {
        total += squad.GetMemberCount();
    }
    return total;
}

void SquadManager::BroadcastOrder(const SquadOrder& order)
{
    for (auto& [id, squad] : m_squads)
    {
        squad.IssueOrder(order);
    }
}

void SquadManager::IssueOrderToSquad(uint32_t squadId, const SquadOrder& order)
{
    Squad* squad = GetSquad(squadId);
    if (squad)
    {
        squad->IssueOrder(order);
    }
}

SquadRole SquadManager::DetermineRoleForClass(uint8_t classId)
{
    // WoW class IDs
    switch (classId)
    {
        case 1:  // Warrior
            return SquadRole::Tank;
        case 2:  // Paladin
            return SquadRole::Tank;  // Could also be healer
        case 3:  // Hunter
            return SquadRole::RangedDPS;
        case 4:  // Rogue
            return SquadRole::MeleeDPS;
        case 5:  // Priest
            return SquadRole::Healer;
        case 6:  // Death Knight
            return SquadRole::Tank;
        case 7:  // Shaman
            return SquadRole::Healer;  // Could also be DPS
        case 8:  // Mage
            return SquadRole::RangedDPS;
        case 9:  // Warlock
            return SquadRole::RangedDPS;
        case 11: // Druid
            return SquadRole::Support;  // Very flexible
        default:
            return SquadRole::MeleeDPS;
    }
}

// =============================================================================
// Default Squad AI Behaviors
// =============================================================================

namespace SquadAI {

void RegisterDefaultBehaviors()
{
    sSquadManager.RegisterSquadAI(CombatBehavior);
    sSquadManager.RegisterSquadAI(HealingBehavior);
    sSquadManager.RegisterSquadAI(MovementBehavior);
    sSquadManager.RegisterSquadAI(FormationBehavior);
}

void CombatBehavior(Squad& squad, uint32_t /*diff*/)
{
    if (!squad.IsInCombat())
        return;

    // If no current order, focus the most targeted enemy
    const SquadOrder& order = squad.GetCurrentOrder();
    if (order.type == OrderType::None)
    {
        EntityId target = squad.GetHighestThreatTarget();
        if (target != InvalidEntityId)
        {
            SquadOrder focusOrder;
            focusOrder.type = OrderType::Focus;
            focusOrder.targetGuid = target.value;  // Use the raw value
            squad.IssueOrder(focusOrder);
        }
    }
}

void HealingBehavior(Squad& squad, uint32_t /*diff*/)
{
    if (!squad.NeedsHealing())
        return;

    EntityId lowestHealth = squad.GetLowestHealthMember();
    if (lowestHealth == InvalidEntityId)
        return;

    // Check if we have a healer in the squad
    for (const auto& member : squad.GetMembers())
    {
        if (member.role == SquadRole::Healer && member.entityId != lowestHealth)
        {
            // Healer should prioritize healing the lowest health member
            // This would send a heal order to the healer bot
            SquadOrder healOrder;
            healOrder.type = OrderType::Heal;
            healOrder.targetGuid = lowestHealth.value;
            healOrder.priority = 10;  // High priority
            // In practice, we'd send this specifically to the healer
            break;
        }
    }
}

void MovementBehavior(Squad& squad, uint32_t /*diff*/)
{
    const SquadOrder& order = squad.GetCurrentOrder();
    if (order.type != OrderType::Move)
        return;

    // Movement is handled by individual bots responding to the order
    // This could trigger formation updates
}

void FormationBehavior(Squad& squad, uint32_t /*diff*/)
{
    // Update formation positions based on leader position
    EntityId leader = squad.GetLeader();
    if (leader == InvalidEntityId)
        return;

    const SquadMemberInfo* leaderInfo = nullptr;
    for (const auto& member : squad.GetMembers())
    {
        if (member.entityId == leader)
        {
            leaderInfo = &member;
            break;
        }
    }

    if (!leaderInfo)
        return;

    // Calculate formation positions for all members
    for (const auto& member : squad.GetMembers())
    {
        if (member.entityId == leader)
            continue;

        float targetX, targetY;
        squad.GetFormationPosition(member.entityId, leaderInfo->x, leaderInfo->y, targetX, targetY);

        // Check if member needs to move to formation position
        float dx = targetX - member.x;
        float dy = targetY - member.y;
        float dist = std::sqrt(dx * dx + dy * dy);

        if (dist > 2.0f)  // Threshold for movement
        {
            // Member should move to formation position
            // This would be sent as a move order
        }
    }
}

} // namespace SquadAI

} // namespace ecs
