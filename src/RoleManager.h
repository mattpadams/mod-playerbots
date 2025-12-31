/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_ROLEMANAGER_H
#define _PLAYERBOT_ROLEMANAGER_H

#include "Player.h"
#include "RoleStatWeights.h"
#include <unordered_map>

// Forward declarations
class PlayerbotAI;
class Group;

// Note: Spec tab enums (HUNTER_TABS, WARRIOR_TABS, etc.) are defined in PlayerbotAI.h
// This file uses those enums via the PlayerbotAI include in RoleManager.cpp

// Group role analysis result
struct GroupRoleAnalysis
{
    uint32 tankCount = 0;
    uint32 healerCount = 0;
    uint32 meleeDpsCount = 0;
    uint32 rangedDpsCount = 0;
    uint32 casterDpsCount = 0;
    uint32 totalMembers = 0;

    bool needsTank() const { return tankCount == 0; }
    bool needsHealer() const { return healerCount == 0; }
    bool needsDps() const { return (meleeDpsCount + rangedDpsCount + casterDpsCount) < 3; }
};

// Role switch request
struct RoleSwitchRequest
{
    GearRole desiredRole;
    uint8 desiredSpecTab;
    bool needsRespec;
    bool needsGearChange;
    uint32 respecCost;  // Copper
    time_t requestTime;
};

class RoleManager
{
public:
    RoleManager(PlayerbotAI* ai);

    // Initialize role manager, called when bot is created/loaded
    void Initialize();

    // Get current role based on spec
    GearRole GetCurrentRole() const;

    // Get the role the bot is currently gearing for
    GearRole GetGearRole() const { return gearRole_; }
    void SetGearRole(GearRole role) { gearRole_ = role; }

    // Analyze group composition
    GroupRoleAnalysis AnalyzeGroupComposition() const;

    // Get recommended role based on group needs
    GearRole GetRecommendedRole() const;

    // Check if role switch is beneficial
    bool ShouldSwitchRole(GearRole targetRole) const;

    // Request a role switch (queues it for when at trainer)
    bool RequestRoleSwitch(GearRole targetRole);

    // Check if there's a pending role switch
    bool HasPendingRoleSwitch() const { return pendingSwitch_.needsRespec; }
    const RoleSwitchRequest& GetPendingSwitch() const { return pendingSwitch_; }

    // Clear pending role switch
    void ClearPendingSwitch() { pendingSwitch_ = {}; }

    // Check if respec is on cooldown
    bool IsRespecOnCooldown() const;

    // Get time until respec is available
    uint32 GetRespecCooldownRemaining() const;

    // Called after successful respec
    void OnRespecComplete();

    // Get spec tab for a given role
    uint8 GetSpecTabForRole(GearRole role) const;

    // Calculate respec cost based on number of respecs
    uint32 CalculateRespecCost() const;

    // Update function called periodically
    void Update();

    // Check if bot can fulfill a specific role
    bool CanFulfillRole(GearRole role) const;

private:
    PlayerbotAI* ai_;
    Player* bot_;

    GearRole gearRole_;           // Current role for gear selection
    RoleSwitchRequest pendingSwitch_;
    time_t lastRespecTime_;
    uint32 respecCount_;          // Tracks number of respecs for cost calculation

    // Helpers
    GearRole DetermineCurrentRoleFromSpec() const;
    bool IsInGroup() const;
    Group* GetGroup() const;
};

#endif
