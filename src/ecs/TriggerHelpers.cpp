/*
 * ECS Trigger Helpers Implementation
 */

#include "TriggerHelpers.h"
#include "ValueCache.h"
#include "BotRegistry.h"
#include "PlayerbotAI.h"
#include "Playerbots.h"
#include "Player.h"
#include "Group.h"
#include "ObjectAccessor.h"
#include "Timer.h"

namespace ecs {

// =============================================================================
// ATTACKER CHECKS
// =============================================================================

uint32_t TriggerHelpers::GetAttackerCount(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    auto attackers = CachedValues::GetAttackers(botAI);
    return static_cast<uint32_t>(attackers.size());
}

uint32_t TriggerHelpers::GetMyAttackerCount(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    Player* bot = botAI->GetBot();
    auto attackers = CachedValues::GetAttackers(botAI);

    uint32_t count = 0;
    for (uint64_t guid : attackers)
    {
        Unit* attacker = ObjectAccessor::GetUnit(*bot, ObjectGuid(guid));
        if (attacker && attacker->GetVictim() == bot)
        {
            ++count;
        }
    }

    return count;
}

bool TriggerHelpers::HasAttackers(PlayerbotAI* botAI)
{
    return GetAttackerCount(botAI) > 0;
}

bool TriggerHelpers::IsBeingAttacked(PlayerbotAI* botAI)
{
    return GetMyAttackerCount(botAI) > 0;
}

std::vector<uint64_t> TriggerHelpers::GetAttackers(PlayerbotAI* botAI)
{
    return CachedValues::GetAttackers(botAI);
}

// =============================================================================
// TARGET CHECKS
// =============================================================================

uint32_t TriggerHelpers::GetPossibleTargetCount(PlayerbotAI* botAI, float range)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    auto targets = CachedValues::GetPossibleTargets(botAI, range);
    return static_cast<uint32_t>(targets.size());
}

bool TriggerHelpers::HasPossibleTargets(PlayerbotAI* botAI, float range)
{
    return GetPossibleTargetCount(botAI, range) > 0;
}

std::vector<uint64_t> TriggerHelpers::GetPossibleTargets(PlayerbotAI* botAI, float range)
{
    return CachedValues::GetPossibleTargets(botAI, range);
}

// =============================================================================
// HEALTH/POWER CHECKS
// =============================================================================

float TriggerHelpers::GetHealthPercent(PlayerbotAI* botAI)
{
    return CachedValues::GetHealthPercent(botAI);
}

float TriggerHelpers::GetPowerPercent(PlayerbotAI* botAI)
{
    return CachedValues::GetPowerPercent(botAI);
}

bool TriggerHelpers::IsHealthBelow(PlayerbotAI* botAI, float threshold)
{
    return GetHealthPercent(botAI) < threshold;
}

bool TriggerHelpers::IsPowerBelow(PlayerbotAI* botAI, float threshold)
{
    return GetPowerPercent(botAI) < threshold;
}

bool TriggerHelpers::IsCriticalHealth(PlayerbotAI* botAI)
{
    return IsHealthBelow(botAI, 15.0f);
}

bool TriggerHelpers::IsLowHealth(PlayerbotAI* botAI)
{
    return IsHealthBelow(botAI, 30.0f);
}

// =============================================================================
// COMBAT STATE CHECKS
// =============================================================================

bool TriggerHelpers::IsInCombat(PlayerbotAI* botAI)
{
    return CachedValues::IsInCombat(botAI);
}

bool TriggerHelpers::IsCasting(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return false;

    // Check ECS component first
    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (entity.IsValid())
    {
        CombatState* combat = sBotRegistry.GetRegistry().GetComponent<CombatState>(entity);
        if (combat)
            return combat->isCasting || combat->isChanneling;
    }

    // Fall back to direct check
    return botAI->GetBot()->IsNonMeleeSpellCast(false);
}

bool TriggerHelpers::IsMoving(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return false;

    // Check ECS component first
    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (entity.IsValid())
    {
        Velocity* vel = sBotRegistry.GetRegistry().GetComponent<Velocity>(entity);
        if (vel)
            return vel->isMoving;
    }

    // Fall back to direct check
    return botAI->GetBot()->isMoving();
}

// =============================================================================
// AOE CHECKS
// =============================================================================

uint32_t TriggerHelpers::CountAttackersInRange(PlayerbotAI* botAI, float x, float y, float z, float range)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    Player* bot = botAI->GetBot();
    auto attackers = CachedValues::GetAttackers(botAI);

    float rangeSq = range * range;
    uint32_t count = 0;

    for (uint64_t guid : attackers)
    {
        Unit* attacker = ObjectAccessor::GetUnit(*bot, ObjectGuid(guid));
        if (!attacker || !attacker->IsAlive())
            continue;

        float dx = attacker->GetPositionX() - x;
        float dy = attacker->GetPositionY() - y;
        float dz = attacker->GetPositionZ() - z;
        float distSq = dx*dx + dy*dy + dz*dz;

        if (distSq <= rangeSq)
        {
            ++count;
        }
    }

    return count;
}

uint32_t TriggerHelpers::CountAttackersNearTarget(PlayerbotAI* botAI, float range)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    // Get current target
    Unit* target = botAI->GetBot()->GetVictim();
    if (!target)
        return 0;

    return CountAttackersInRange(
        botAI,
        target->GetPositionX(),
        target->GetPositionY(),
        target->GetPositionZ(),
        range
    );
}

// =============================================================================
// PARTY/GROUP CHECKS
// =============================================================================

uint32_t TriggerHelpers::GetPartyMemberCount(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return 1;

    Group* group = botAI->GetBot()->GetGroup();
    if (!group)
        return 1;

    return group->GetMembersCount();
}

bool TriggerHelpers::AnyPartyMemberNeedsHealing(PlayerbotAI* botAI)
{
    return CountPartyMembersBelowHealth(botAI, 90.0f) > 0;
}

uint32_t TriggerHelpers::CountPartyMembersBelowHealth(PlayerbotAI* botAI, float threshold)
{
    if (!botAI || !botAI->GetBot())
        return 0;

    Player* bot = botAI->GetBot();
    Group* group = bot->GetGroup();

    if (!group)
    {
        // Solo - just check self
        return GetHealthPercent(botAI) < threshold ? 1 : 0;
    }

    uint32_t count = 0;
    Group::MemberSlotList const& members = group->GetMemberSlots();

    for (auto& memberSlot : members)
    {
        Player* member = ObjectAccessor::FindPlayer(memberSlot.guid);
        if (!member || !member->IsAlive())
            continue;

        if (member->GetMapId() != bot->GetMapId())
            continue;

        // Use ECS cache if available for this member
        PlayerbotAI* memberAI = GET_PLAYERBOT_AI(member);
        float healthPct;

        if (memberAI)
        {
            healthPct = GetHealthPercent(memberAI);
        }
        else
        {
            healthPct = member->GetHealthPct();
        }

        if (healthPct < threshold)
        {
            ++count;
        }
    }

    return count;
}

} // namespace ecs
