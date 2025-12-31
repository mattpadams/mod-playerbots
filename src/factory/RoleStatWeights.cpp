/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "RoleStatWeights.h"
#include "SharedDefines.h"

RoleStatWeights::RoleStatWeights()
{
    initialized_ = false;
}

void RoleStatWeights::Initialize()
{
    if (initialized_)
        return;

    InitializeProfiles();
    initialized_ = true;
}

void RoleStatWeights::InitializeProfiles()
{
    // Tank Profile - Focus on survivability and threat
    {
        RoleStatWeightProfile& tank = profiles_[static_cast<uint8>(GearRole::ROLE_TANK)];
        tank.role = GearRole::ROLE_TANK;

        // Primary stats
        tank.weights[STATS_TYPE_STAMINA] = 3.5f;      // Health pool is critical
        tank.weights[STATS_TYPE_DEFENSE] = 2.5f;      // Defense rating for crit immunity
        tank.weights[STATS_TYPE_AGILITY] = 2.0f;      // Dodge, armor, crit
        tank.weights[STATS_TYPE_STRENGTH] = 1.5f;     // Block value, threat (warriors/paladins)

        // Defensive stats
        tank.weights[STATS_TYPE_ARMOR] = 1.8f;        // Physical damage reduction
        tank.weights[STATS_TYPE_DODGE] = 2.0f;        // Avoidance
        tank.weights[STATS_TYPE_PARRY] = 2.0f;        // Avoidance (warriors/paladins)
        tank.weights[STATS_TYPE_BLOCK_VALUE] = 1.5f;  // Block effectiveness
        tank.weights[STATS_TYPE_BLOCK_RATING] = 1.5f; // Block chance
        tank.weights[STATS_TYPE_RESILIENCE] = 0.5f;   // PvP, minor value in PvE

        // Threat stats
        tank.weights[STATS_TYPE_HIT] = 1.8f;          // Threat reliability
        tank.weights[STATS_TYPE_EXPERTISE] = 1.5f;   // Reduce parry/dodge
        tank.weights[STATS_TYPE_ATTACK_POWER] = 0.8f; // Threat generation
        tank.weights[STATS_TYPE_CRIT] = 0.6f;         // Minor threat boost

        // Recovery
        tank.weights[STATS_TYPE_HEALTH_REGENERATION] = 1.0f;

        // Low value stats for tanks
        tank.weights[STATS_TYPE_INTELLECT] = 0.1f;
        tank.weights[STATS_TYPE_SPIRIT] = 0.1f;
        tank.weights[STATS_TYPE_SPELL_POWER] = 0.0f;
        tank.weights[STATS_TYPE_HEAL_POWER] = 0.0f;
        tank.weights[STATS_TYPE_MANA_REGENERATION] = 0.1f;
    }

    // Healer Profile - Focus on healing output and mana sustainability
    {
        RoleStatWeightProfile& healer = profiles_[static_cast<uint8>(GearRole::ROLE_HEALER)];
        healer.role = GearRole::ROLE_HEALER;

        // Primary stats
        healer.weights[STATS_TYPE_HEAL_POWER] = 1.0f;        // Direct healing increase
        healer.weights[STATS_TYPE_INTELLECT] = 0.9f;         // Mana pool, spell crit
        healer.weights[STATS_TYPE_MANA_REGENERATION] = 0.9f; // MP5 for sustained healing
        healer.weights[STATS_TYPE_SPIRIT] = 0.6f;            // Out-of-FSR regen
        healer.weights[STATS_TYPE_STAMINA] = 0.5f;           // Survivability

        // Secondary stats
        healer.weights[STATS_TYPE_SPELL_POWER] = 0.5f;       // Some healing spells scale
        healer.weights[STATS_TYPE_CRIT] = 0.4f;              // Spell crit for big heals
        healer.weights[STATS_TYPE_HASTE] = 0.3f;             // Faster casts (Classic has less)

        // Low value stats for healers
        healer.weights[STATS_TYPE_STRENGTH] = 0.0f;
        healer.weights[STATS_TYPE_AGILITY] = 0.1f;
        healer.weights[STATS_TYPE_ATTACK_POWER] = 0.0f;
        healer.weights[STATS_TYPE_HIT] = 0.1f;
        healer.weights[STATS_TYPE_DEFENSE] = 0.1f;
        healer.weights[STATS_TYPE_ARMOR] = 0.2f;
    }

    // Melee DPS Profile - Focus on physical damage output
    {
        RoleStatWeightProfile& melee = profiles_[static_cast<uint8>(GearRole::ROLE_MELEE_DPS)];
        melee.role = GearRole::ROLE_MELEE_DPS;

        // Primary stats
        melee.weights[STATS_TYPE_STRENGTH] = 2.3f;           // Attack power (most classes)
        melee.weights[STATS_TYPE_AGILITY] = 1.8f;            // Crit, dodge, AP (rogues)
        melee.weights[STATS_TYPE_HIT] = 2.0f;                // Hit cap is critical
        melee.weights[STATS_TYPE_CRIT] = 1.5f;               // Damage multiplier
        melee.weights[STATS_TYPE_ATTACK_POWER] = 1.2f;       // Direct damage

        // Secondary stats
        melee.weights[STATS_TYPE_EXPERTISE] = 1.3f;          // Reduce parry/dodge
        melee.weights[STATS_TYPE_ARMOR_PENETRATION] = 1.0f;  // Late-game scaling
        melee.weights[STATS_TYPE_HASTE] = 0.8f;              // Attack speed
        melee.weights[STATS_TYPE_MELEE_DPS] = 2.0f;          // Weapon DPS important

        // Survivability (minor)
        melee.weights[STATS_TYPE_STAMINA] = 0.4f;
        melee.weights[STATS_TYPE_ARMOR] = 0.2f;

        // Low value stats for melee
        melee.weights[STATS_TYPE_INTELLECT] = 0.0f;
        melee.weights[STATS_TYPE_SPIRIT] = 0.0f;
        melee.weights[STATS_TYPE_SPELL_POWER] = 0.0f;
        melee.weights[STATS_TYPE_HEAL_POWER] = 0.0f;
    }

    // Ranged DPS Profile - Hunters
    {
        RoleStatWeightProfile& ranged = profiles_[static_cast<uint8>(GearRole::ROLE_RANGED_DPS)];
        ranged.role = GearRole::ROLE_RANGED_DPS;

        // Primary stats
        ranged.weights[STATS_TYPE_AGILITY] = 2.5f;           // Main stat for hunters
        ranged.weights[STATS_TYPE_HIT] = 2.2f;               // Hit cap is critical
        ranged.weights[STATS_TYPE_CRIT] = 1.6f;              // Damage multiplier
        ranged.weights[STATS_TYPE_ATTACK_POWER] = 1.3f;      // Ranged attack power
        ranged.weights[STATS_TYPE_RANGED_DPS] = 2.5f;        // Ranged weapon DPS

        // Secondary stats
        ranged.weights[STATS_TYPE_STAMINA] = 0.4f;           // Survivability
        ranged.weights[STATS_TYPE_HASTE] = 0.7f;             // Attack speed
        ranged.weights[STATS_TYPE_INTELLECT] = 0.3f;         // Mana pool for hunters

        // Low value stats for ranged
        ranged.weights[STATS_TYPE_STRENGTH] = 0.1f;          // Minimal melee value
        ranged.weights[STATS_TYPE_SPIRIT] = 0.1f;
        ranged.weights[STATS_TYPE_SPELL_POWER] = 0.0f;
        ranged.weights[STATS_TYPE_HEAL_POWER] = 0.0f;
        ranged.weights[STATS_TYPE_DEFENSE] = 0.0f;
    }

    // Caster DPS Profile - Mages, Warlocks, Shadow Priests, Balance Druids, Elemental Shamans
    {
        RoleStatWeightProfile& caster = profiles_[static_cast<uint8>(GearRole::ROLE_CASTER_DPS)];
        caster.role = GearRole::ROLE_CASTER_DPS;

        // Primary stats
        caster.weights[STATS_TYPE_SPELL_POWER] = 1.0f;       // Direct damage increase
        caster.weights[STATS_TYPE_HIT] = 1.1f;               // Spell hit cap is critical
        caster.weights[STATS_TYPE_CRIT] = 0.8f;              // Spell crit
        caster.weights[STATS_TYPE_INTELLECT] = 0.3f;         // Mana pool, minor crit

        // Secondary stats
        caster.weights[STATS_TYPE_SPELL_PENETRATION] = 0.6f; // PvP/resist fights
        caster.weights[STATS_TYPE_HASTE] = 0.5f;             // Cast speed
        caster.weights[STATS_TYPE_MANA_REGENERATION] = 0.4f; // MP5 for sustained fights
        caster.weights[STATS_TYPE_SPIRIT] = 0.3f;            // Mana regen

        // Survivability (minor)
        caster.weights[STATS_TYPE_STAMINA] = 0.3f;
        caster.weights[STATS_TYPE_ARMOR] = 0.1f;

        // Low value stats for casters
        caster.weights[STATS_TYPE_STRENGTH] = 0.0f;
        caster.weights[STATS_TYPE_AGILITY] = 0.0f;
        caster.weights[STATS_TYPE_ATTACK_POWER] = 0.0f;
        caster.weights[STATS_TYPE_HEAL_POWER] = 0.1f;        // Minor benefit for off-healing
        caster.weights[STATS_TYPE_DEFENSE] = 0.0f;
    }
}

const RoleStatWeightProfile& RoleStatWeights::GetProfile(GearRole role) const
{
    uint8 index = static_cast<uint8>(role);
    if (index >= static_cast<uint8>(GearRole::ROLE_MAX))
        index = static_cast<uint8>(GearRole::ROLE_MELEE_DPS); // Fallback

    return profiles_[index];
}

GearRole RoleStatWeights::GetRecommendedRole(Player* player, bool inGroup, bool hasTank, bool hasHealer) const
{
    if (!player)
        return GearRole::ROLE_MELEE_DPS;

    uint8 playerClass = player->getClass();

    // If not in a group, use default DPS role for the class
    if (!inGroup)
        return GetDefaultDpsRole(playerClass);

    // Group composition logic
    // If group needs a tank and this class can tank, recommend tank
    if (!hasTank && CanClassTank(playerClass))
        return GearRole::ROLE_TANK;

    // If group needs a healer and this class can heal, recommend healer
    if (!hasHealer && CanClassHeal(playerClass))
        return GearRole::ROLE_HEALER;

    // Otherwise, default to DPS role for the class
    return GetDefaultDpsRole(playerClass);
}

GearRole RoleStatWeights::GetDefaultDpsRole(uint8 playerClass) const
{
    switch (playerClass)
    {
        case CLASS_WARRIOR:
        case CLASS_ROGUE:
            return GearRole::ROLE_MELEE_DPS;

        case CLASS_PALADIN:
            return GearRole::ROLE_MELEE_DPS; // Retribution

        case CLASS_HUNTER:
            return GearRole::ROLE_RANGED_DPS;

        case CLASS_SHAMAN:
            return GearRole::ROLE_CASTER_DPS; // Elemental preferred, could also be Enhancement

        case CLASS_DRUID:
            return GearRole::ROLE_MELEE_DPS; // Feral cat, could also be Balance

        case CLASS_MAGE:
        case CLASS_WARLOCK:
            return GearRole::ROLE_CASTER_DPS;

        case CLASS_PRIEST:
            return GearRole::ROLE_CASTER_DPS; // Shadow

        default:
            return GearRole::ROLE_MELEE_DPS;
    }
}

bool RoleStatWeights::CanClassTank(uint8 playerClass) const
{
    switch (playerClass)
    {
        case CLASS_WARRIOR:
        case CLASS_PALADIN:
        case CLASS_DRUID:
            return true;
        default:
            return false;
    }
}

bool RoleStatWeights::CanClassHeal(uint8 playerClass) const
{
    switch (playerClass)
    {
        case CLASS_PRIEST:
        case CLASS_PALADIN:
        case CLASS_SHAMAN:
        case CLASS_DRUID:
            return true;
        default:
            return false;
    }
}

void RoleStatWeights::ApplyClassAdjustments(uint8 playerClass, GearRole role, float* weights) const
{
    if (!weights)
        return;

    // Apply class-specific adjustments on top of role weights
    switch (role)
    {
        case GearRole::ROLE_TANK:
            // Druid tanks don't use shields - no block stats
            if (playerClass == CLASS_DRUID)
            {
                weights[STATS_TYPE_BLOCK_VALUE] = 0.0f;
                weights[STATS_TYPE_BLOCK_RATING] = 0.0f;
                weights[STATS_TYPE_PARRY] = 0.0f;
                // Druids benefit more from armor and agility
                weights[STATS_TYPE_ARMOR] *= 1.5f;
                weights[STATS_TYPE_AGILITY] *= 1.3f;
            }
            // Paladin tanks benefit from intellect for mana
            else if (playerClass == CLASS_PALADIN)
            {
                weights[STATS_TYPE_INTELLECT] = 0.5f;
                weights[STATS_TYPE_MANA_REGENERATION] = 0.4f;
                weights[STATS_TYPE_SPELL_POWER] = 0.3f; // Consecration threat
            }
            break;

        case GearRole::ROLE_HEALER:
            // Paladin healers focus on crit for illumination
            if (playerClass == CLASS_PALADIN)
            {
                weights[STATS_TYPE_CRIT] = 0.7f;
                weights[STATS_TYPE_STAMINA] = 0.6f; // Plate wearers
            }
            // Druid healers benefit from spirit for innervate
            else if (playerClass == CLASS_DRUID)
            {
                weights[STATS_TYPE_SPIRIT] = 0.8f;
            }
            // Priest healers
            else if (playerClass == CLASS_PRIEST)
            {
                weights[STATS_TYPE_SPIRIT] = 0.7f;
            }
            // Shaman healers - mana tide and water shield
            else if (playerClass == CLASS_SHAMAN)
            {
                weights[STATS_TYPE_MANA_REGENERATION] = 1.0f;
            }
            break;

        case GearRole::ROLE_MELEE_DPS:
            // Rogues scale more with agility
            if (playerClass == CLASS_ROGUE)
            {
                weights[STATS_TYPE_AGILITY] = 2.5f;
                weights[STATS_TYPE_STRENGTH] = 1.0f;
            }
            // Feral druids
            else if (playerClass == CLASS_DRUID)
            {
                weights[STATS_TYPE_AGILITY] = 2.2f;
                weights[STATS_TYPE_STRENGTH] = 1.8f;
            }
            // Enhancement shamans
            else if (playerClass == CLASS_SHAMAN)
            {
                weights[STATS_TYPE_INTELLECT] = 0.3f;
                weights[STATS_TYPE_SPELL_POWER] = 0.4f; // Nature damage
            }
            // Retribution paladins
            else if (playerClass == CLASS_PALADIN)
            {
                weights[STATS_TYPE_INTELLECT] = 0.3f;
                weights[STATS_TYPE_SPELL_POWER] = 0.5f; // Holy damage
            }
            break;

        case GearRole::ROLE_CASTER_DPS:
            // Shadow priests - spirit is good for sustained DPS
            if (playerClass == CLASS_PRIEST)
            {
                weights[STATS_TYPE_SPIRIT] = 0.5f;
            }
            // Warlocks - life tap benefits from spirit
            else if (playerClass == CLASS_WARLOCK)
            {
                weights[STATS_TYPE_SPIRIT] = 0.4f;
                weights[STATS_TYPE_STAMINA] = 0.5f; // Life tap
            }
            // Balance druids - mana is important
            else if (playerClass == CLASS_DRUID)
            {
                weights[STATS_TYPE_SPIRIT] = 0.5f;
                weights[STATS_TYPE_MANA_REGENERATION] = 0.6f;
            }
            // Elemental shamans
            else if (playerClass == CLASS_SHAMAN)
            {
                weights[STATS_TYPE_MANA_REGENERATION] = 0.5f;
            }
            break;

        default:
            break;
    }
}

float RoleStatWeights::GetLevelScaledWeight(float baseWeight, uint32 level, StatsType stat) const
{
    // Early levels (1-19): Stamina and primary stats matter most
    // Mid levels (20-39): Secondary stats start gaining value
    // High levels (40-60): Hit rating and specialization stats become critical

    float levelMultiplier = 1.0f;

    if (level < 20)
    {
        // Early game - reduce importance of hit/crit/expertise
        switch (stat)
        {
            case STATS_TYPE_HIT:
            case STATS_TYPE_CRIT:
            case STATS_TYPE_EXPERTISE:
            case STATS_TYPE_ARMOR_PENETRATION:
            case STATS_TYPE_SPELL_PENETRATION:
            case STATS_TYPE_HASTE:
            case STATS_TYPE_RESILIENCE:
                levelMultiplier = 0.3f;
                break;
            case STATS_TYPE_DEFENSE:
            case STATS_TYPE_DODGE:
            case STATS_TYPE_PARRY:
            case STATS_TYPE_BLOCK_RATING:
                levelMultiplier = 0.5f;
                break;
            default:
                levelMultiplier = 1.0f;
                break;
        }
    }
    else if (level < 40)
    {
        // Mid game - secondary stats gain value
        switch (stat)
        {
            case STATS_TYPE_HIT:
            case STATS_TYPE_CRIT:
            case STATS_TYPE_EXPERTISE:
                levelMultiplier = 0.7f;
                break;
            case STATS_TYPE_ARMOR_PENETRATION:
            case STATS_TYPE_SPELL_PENETRATION:
            case STATS_TYPE_HASTE:
                levelMultiplier = 0.5f;
                break;
            default:
                levelMultiplier = 1.0f;
                break;
        }
    }
    // Level 40+ uses base weights as intended

    return baseWeight * levelMultiplier;
}
