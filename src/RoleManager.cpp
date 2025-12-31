/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "RoleManager.h"
#include "AiFactory.h"
#include "Group.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "SharedDefines.h"

RoleManager::RoleManager(PlayerbotAI* ai)
    : ai_(ai)
    , bot_(ai ? ai->GetBot() : nullptr)
    , gearRole_(GearRole::ROLE_MELEE_DPS)
    , lastRespecTime_(0)
    , respecCount_(0)
{
    pendingSwitch_ = {};
}

void RoleManager::Initialize()
{
    if (!bot_)
        return;

    // Set initial gear role based on current spec
    gearRole_ = DetermineCurrentRoleFromSpec();
}

GearRole RoleManager::GetCurrentRole() const
{
    return DetermineCurrentRoleFromSpec();
}

GearRole RoleManager::DetermineCurrentRoleFromSpec() const
{
    if (!bot_)
        return GearRole::ROLE_MELEE_DPS;

    // Use existing PlayerbotAI methods to determine role from current spec
    if (PlayerbotAI::IsTank(bot_))
        return GearRole::ROLE_TANK;
    if (PlayerbotAI::IsHeal(bot_))
        return GearRole::ROLE_HEALER;
    if (PlayerbotAI::IsCaster(bot_))
        return GearRole::ROLE_CASTER_DPS;
    if (PlayerbotAI::IsRanged(bot_))
        return GearRole::ROLE_RANGED_DPS;

    return GearRole::ROLE_MELEE_DPS;
}

GroupRoleAnalysis RoleManager::AnalyzeGroupComposition() const
{
    GroupRoleAnalysis analysis;

    if (!bot_)
        return analysis;

    Group* group = GetGroup();
    if (!group)
    {
        // Solo - just count ourselves
        analysis.totalMembers = 1;
        switch (GetCurrentRole())
        {
            case GearRole::ROLE_TANK: analysis.tankCount = 1; break;
            case GearRole::ROLE_HEALER: analysis.healerCount = 1; break;
            case GearRole::ROLE_MELEE_DPS: analysis.meleeDpsCount = 1; break;
            case GearRole::ROLE_RANGED_DPS: analysis.rangedDpsCount = 1; break;
            case GearRole::ROLE_CASTER_DPS: analysis.casterDpsCount = 1; break;
            default: break;
        }
        return analysis;
    }

    // Analyze each group member
    for (GroupReference* ref = group->GetFirstMember(); ref; ref = ref->next())
    {
        Player* member = ref->GetSource();
        if (!member || !member->IsInWorld())
            continue;

        analysis.totalMembers++;

        // Determine member's role
        if (PlayerbotAI::IsTank(member))
            analysis.tankCount++;
        else if (PlayerbotAI::IsHeal(member))
            analysis.healerCount++;
        else if (PlayerbotAI::IsCaster(member))
            analysis.casterDpsCount++;
        else if (PlayerbotAI::IsRanged(member))
            analysis.rangedDpsCount++;
        else
            analysis.meleeDpsCount++;
    }

    return analysis;
}

GearRole RoleManager::GetRecommendedRole() const
{
    if (!bot_)
        return GearRole::ROLE_MELEE_DPS;

    uint8 playerClass = bot_->getClass();
    GroupRoleAnalysis analysis = AnalyzeGroupComposition();

    // If in a group, check what's needed
    if (analysis.totalMembers > 1)
    {
        // Group needs a tank and we can tank
        if (analysis.needsTank() && sRoleStatWeights->CanClassTank(playerClass))
            return GearRole::ROLE_TANK;

        // Group needs a healer and we can heal
        if (analysis.needsHealer() && sRoleStatWeights->CanClassHeal(playerClass))
            return GearRole::ROLE_HEALER;
    }

    // Default to class's preferred DPS role
    return sRoleStatWeights->GetDefaultDpsRole(playerClass);
}

bool RoleManager::ShouldSwitchRole(GearRole targetRole) const
{
    if (!bot_)
        return false;

    // Don't switch if we're already in the target role
    if (GetCurrentRole() == targetRole)
        return false;

    // Don't switch if on cooldown
    if (IsRespecOnCooldown())
        return false;

    // Don't switch if we can't fulfill the target role
    if (!CanFulfillRole(targetRole))
        return false;

    // Check if the switch makes sense for group composition
    GroupRoleAnalysis analysis = AnalyzeGroupComposition();

    switch (targetRole)
    {
        case GearRole::ROLE_TANK:
            // Only switch to tank if group needs one
            return analysis.needsTank();
        case GearRole::ROLE_HEALER:
            // Only switch to healer if group needs one
            return analysis.needsHealer();
        default:
            // Always allow switching to DPS if we're not needed as tank/healer
            return true;
    }
}

bool RoleManager::RequestRoleSwitch(GearRole targetRole)
{
    if (!ShouldSwitchRole(targetRole))
        return false;

    pendingSwitch_.desiredRole = targetRole;
    pendingSwitch_.desiredSpecTab = GetSpecTabForRole(targetRole);
    pendingSwitch_.needsRespec = (GetCurrentRole() != targetRole);
    pendingSwitch_.needsGearChange = true;
    pendingSwitch_.respecCost = CalculateRespecCost();
    pendingSwitch_.requestTime = time(nullptr);

    return true;
}

bool RoleManager::IsRespecOnCooldown() const
{
    if (lastRespecTime_ == 0)
        return false;

    uint32 cooldownMinutes = sPlayerbotAIConfig->respecCooldownMinutes;
    if (cooldownMinutes == 0)
        return false;

    time_t cooldownSeconds = cooldownMinutes * 60;
    return (time(nullptr) - lastRespecTime_) < cooldownSeconds;
}

uint32 RoleManager::GetRespecCooldownRemaining() const
{
    if (!IsRespecOnCooldown())
        return 0;

    uint32 cooldownMinutes = sPlayerbotAIConfig->respecCooldownMinutes;
    time_t cooldownSeconds = cooldownMinutes * 60;
    time_t elapsed = time(nullptr) - lastRespecTime_;

    return static_cast<uint32>(cooldownSeconds - elapsed);
}

void RoleManager::OnRespecComplete()
{
    lastRespecTime_ = time(nullptr);
    respecCount_++;

    // Update gear role to match new spec
    gearRole_ = DetermineCurrentRoleFromSpec();

    // Clear pending switch
    ClearPendingSwitch();
}

uint8 RoleManager::GetSpecTabForRole(GearRole role) const
{
    if (!bot_)
        return 0;

    uint8 playerClass = bot_->getClass();

    switch (role)
    {
        case GearRole::ROLE_TANK:
            switch (playerClass)
            {
                case CLASS_WARRIOR: return WARRIOR_TAB_PROTECTION;
                case CLASS_PALADIN: return PALADIN_TAB_PROTECTION;
                case CLASS_DRUID: return DRUID_TAB_FERAL; // Bear
                default: return 0;
            }
            break;

        case GearRole::ROLE_HEALER:
            switch (playerClass)
            {
                case CLASS_PRIEST: return PRIEST_TAB_HOLY;
                case CLASS_PALADIN: return PALADIN_TAB_HOLY;
                case CLASS_SHAMAN: return SHAMAN_TAB_RESTORATION;
                case CLASS_DRUID: return DRUID_TAB_RESTORATION;
                default: return 0;
            }
            break;

        case GearRole::ROLE_MELEE_DPS:
            switch (playerClass)
            {
                case CLASS_WARRIOR: return WARRIOR_TAB_FURY;
                case CLASS_PALADIN: return PALADIN_TAB_RETRIBUTION;
                case CLASS_ROGUE: return ROGUE_TAB_COMBAT;
                case CLASS_SHAMAN: return SHAMAN_TAB_ENHANCEMENT;
                case CLASS_DRUID: return DRUID_TAB_FERAL; // Cat
                default: return 0;
            }
            break;

        case GearRole::ROLE_RANGED_DPS:
            switch (playerClass)
            {
                case CLASS_HUNTER: return HUNTER_TAB_MARKSMANSHIP;
                default: return 0;
            }
            break;

        case GearRole::ROLE_CASTER_DPS:
            switch (playerClass)
            {
                case CLASS_MAGE: return MAGE_TAB_FROST;
                case CLASS_WARLOCK: return WARLOCK_TAB_AFFLICTION;
                case CLASS_PRIEST: return PRIEST_TAB_SHADOW;
                case CLASS_SHAMAN: return SHAMAN_TAB_ELEMENTAL;
                case CLASS_DRUID: return DRUID_TAB_BALANCE;
                default: return 0;
            }
            break;

        default:
            return 0;
    }

    return 0;
}

uint32 RoleManager::CalculateRespecCost() const
{
    // Classic respec cost formula:
    // 1g for first respec, increases by 5g each time up to 50g cap
    // Decays by 5g per month (not implemented for simplicity)
    const uint32 BASE_COST = 10000;      // 1 gold in copper
    const uint32 INCREMENT = 50000;       // 5 gold increment
    const uint32 MAX_COST = 500000;       // 50 gold cap

    uint32 cost = BASE_COST + (respecCount_ * INCREMENT);
    return std::min(cost, MAX_COST);
}

void RoleManager::Update()
{
    // Periodic update - could be used for automatic role evaluation
    // Currently a placeholder for future enhancements
}

bool RoleManager::CanFulfillRole(GearRole role) const
{
    if (!bot_)
        return false;

    uint8 playerClass = bot_->getClass();

    switch (role)
    {
        case GearRole::ROLE_TANK:
            return sRoleStatWeights->CanClassTank(playerClass);

        case GearRole::ROLE_HEALER:
            return sRoleStatWeights->CanClassHeal(playerClass);

        case GearRole::ROLE_MELEE_DPS:
            // All classes can melee DPS to some degree
            return true;

        case GearRole::ROLE_RANGED_DPS:
            // Only hunters are true ranged physical DPS
            return playerClass == CLASS_HUNTER;

        case GearRole::ROLE_CASTER_DPS:
            // Casters: Mage, Warlock, Shadow Priest, Balance Druid, Elemental Shaman
            return playerClass == CLASS_MAGE ||
                   playerClass == CLASS_WARLOCK ||
                   playerClass == CLASS_PRIEST ||
                   playerClass == CLASS_DRUID ||
                   playerClass == CLASS_SHAMAN;

        default:
            return false;
    }
}

bool RoleManager::IsInGroup() const
{
    return bot_ && bot_->GetGroup() != nullptr;
}

Group* RoleManager::GetGroup() const
{
    return bot_ ? bot_->GetGroup() : nullptr;
}
