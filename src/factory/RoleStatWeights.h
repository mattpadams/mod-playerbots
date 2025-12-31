/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_ROLESTATWEIGHTS_H
#define _PLAYERBOT_ROLESTATWEIGHTS_H

#include "Player.h"
#include "StatsCollector.h"

// Role types for gear selection (independent of spec)
enum class GearRole : uint8
{
    ROLE_TANK = 0,
    ROLE_HEALER = 1,
    ROLE_MELEE_DPS = 2,
    ROLE_RANGED_DPS = 3,
    ROLE_CASTER_DPS = 4,
    ROLE_MAX = 5
};

// Role-based stat weight profile
struct RoleStatWeightProfile
{
    GearRole role;
    float weights[STATS_TYPE_MAX];

    RoleStatWeightProfile()
    {
        role = GearRole::ROLE_MELEE_DPS;
        for (uint32 i = 0; i < STATS_TYPE_MAX; ++i)
            weights[i] = 0.0f;
    }
};

class RoleStatWeights
{
public:
    static RoleStatWeights* instance()
    {
        static RoleStatWeights instance;
        return &instance;
    }

    void Initialize();

    // Get weight profile for a specific role
    const RoleStatWeightProfile& GetProfile(GearRole role) const;

    // Get recommended role based on class capabilities and group needs
    GearRole GetRecommendedRole(Player* player, bool inGroup, bool hasTank, bool hasHealer) const;

    // Get default DPS role for a class
    GearRole GetDefaultDpsRole(uint8 playerClass) const;

    // Check if class can fulfill a role
    bool CanClassTank(uint8 playerClass) const;
    bool CanClassHeal(uint8 playerClass) const;

    // Get class-specific weight adjustments for a role
    void ApplyClassAdjustments(uint8 playerClass, GearRole role, float* weights) const;

    // Level scaling for Classic (1-60)
    float GetLevelScaledWeight(float baseWeight, uint32 level, StatsType stat) const;

private:
    RoleStatWeights();
    void InitializeProfiles();

    RoleStatWeightProfile profiles_[static_cast<uint8>(GearRole::ROLE_MAX)];
    bool initialized_ = false;
};

#define sRoleStatWeights RoleStatWeights::instance()

#endif
