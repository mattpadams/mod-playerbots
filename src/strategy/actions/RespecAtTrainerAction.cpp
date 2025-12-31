/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "RespecAtTrainerAction.h"
#include "AiFactory.h"
#include "BudgetValues.h"
#include "CellImpl.h"
#include "Creature.h"
#include "Event.h"
#include "GridNotifiers.h"
#include "GridNotifiersImpl.h"
#include "ObjectGuid.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "PlayerbotFactory.h"
#include "Playerbots.h"
#include "RoleManager.h"
#include "SharedDefines.h"

bool RespecAtTrainerAction::Execute(Event event)
{
    // Get the bot's role manager (this would need to be added to PlayerbotAI)
    // For now, we'll use the event parameter to determine target spec
    std::string param = event.getParam();

    Creature* trainer = FindClassTrainer();
    if (!trainer)
    {
        botAI->TellError("No class trainer nearby for respec");
        return false;
    }

    uint32 respecCost = GetRespecCost();
    if (!CanAffordRespec(respecCost))
    {
        botAI->TellError("Cannot afford respec");
        return false;
    }

    // Determine target spec tab from parameter or recommended role
    uint8 targetSpecTab = 0;
    if (!param.empty())
    {
        // Parse spec from command parameter (e.g., "tank", "healer", "dps")
        if (param == "tank")
        {
            GearRole role = GearRole::ROLE_TANK;
            if (!sRoleStatWeights->CanClassTank(bot->getClass()))
            {
                botAI->TellError("This class cannot tank");
                return false;
            }
            // Get spec tab for tank role
            switch (bot->getClass())
            {
                case CLASS_WARRIOR: targetSpecTab = 2; break; // Protection
                case CLASS_PALADIN: targetSpecTab = 1; break; // Protection
                case CLASS_DRUID: targetSpecTab = 1; break;   // Feral
                default: return false;
            }
        }
        else if (param == "healer" || param == "heal")
        {
            if (!sRoleStatWeights->CanClassHeal(bot->getClass()))
            {
                botAI->TellError("This class cannot heal");
                return false;
            }
            switch (bot->getClass())
            {
                case CLASS_PRIEST: targetSpecTab = 1; break;  // Holy
                case CLASS_PALADIN: targetSpecTab = 0; break; // Holy
                case CLASS_SHAMAN: targetSpecTab = 2; break;  // Restoration
                case CLASS_DRUID: targetSpecTab = 2; break;   // Restoration
                default: return false;
            }
        }
        else if (param == "dps")
        {
            GearRole role = sRoleStatWeights->GetDefaultDpsRole(bot->getClass());
            switch (bot->getClass())
            {
                case CLASS_WARRIOR: targetSpecTab = 1; break;  // Fury
                case CLASS_PALADIN: targetSpecTab = 2; break;  // Retribution
                case CLASS_ROGUE: targetSpecTab = 1; break;    // Combat
                case CLASS_HUNTER: targetSpecTab = 1; break;   // Marksmanship
                case CLASS_PRIEST: targetSpecTab = 2; break;   // Shadow
                case CLASS_SHAMAN: targetSpecTab = 0; break;   // Elemental
                case CLASS_MAGE: targetSpecTab = 2; break;     // Frost
                case CLASS_WARLOCK: targetSpecTab = 0; break;  // Affliction
                case CLASS_DRUID: targetSpecTab = 1; break;    // Feral
                default: targetSpecTab = 0; break;
            }
        }
        else
        {
            // Try to parse as spec tab number
            targetSpecTab = atoi(param.c_str());
        }
    }
    else
    {
        // Use recommended role based on group composition
        GearRole desiredRole = AiFactory::GetDesiredGearRole(bot);
        switch (desiredRole)
        {
            case GearRole::ROLE_TANK:
                switch (bot->getClass())
                {
                    case CLASS_WARRIOR: targetSpecTab = 2; break;
                    case CLASS_PALADIN: targetSpecTab = 1; break;
                    case CLASS_DRUID: targetSpecTab = 1; break;
                    default: break;
                }
                break;
            case GearRole::ROLE_HEALER:
                switch (bot->getClass())
                {
                    case CLASS_PRIEST: targetSpecTab = 1; break;
                    case CLASS_PALADIN: targetSpecTab = 0; break;
                    case CLASS_SHAMAN: targetSpecTab = 2; break;
                    case CLASS_DRUID: targetSpecTab = 2; break;
                    default: break;
                }
                break;
            default:
                // Keep current spec for DPS
                targetSpecTab = AiFactory::GetPlayerSpecTab(bot);
                break;
        }
    }

    return DoRespec(trainer, targetSpecTab);
}

bool RespecAtTrainerAction::isPossible()
{
    // Check if bot level is high enough for respec to matter
    if (bot->GetLevel() < sPlayerbotAIConfig->roleSwitchMinLevel)
        return false;

    return FindClassTrainer() != nullptr;
}

bool RespecAtTrainerAction::isUseful()
{
    // Check if dynamic role switching is enabled
    if (!sPlayerbotAIConfig->dynamicRoleSwitchingEnabled)
        return false;

    // Check if we need to respec based on desired role
    GearRole currentRole = AiFactory::GetCurrentGearRole(bot);
    GearRole desiredRole = AiFactory::GetDesiredGearRole(bot);

    // Only useful if we need to change roles
    return currentRole != desiredRole;
}

Creature* RespecAtTrainerAction::FindClassTrainer() const
{
    // Search for a nearby class trainer of the bot's class
    float range = INTERACTION_DISTANCE * 2;

    std::list<Unit*> targets;
    Acore::AnyUnitInObjectRangeCheck u_check(bot, range);
    Acore::UnitListSearcher<Acore::AnyUnitInObjectRangeCheck> searcher(bot, targets, u_check);
    Cell::VisitObjects(bot, searcher, range);

    for (Unit* unit : targets)
    {
        Creature* creature = unit->ToCreature();
        if (!creature || !creature->IsAlive())
            continue;

        // Check if it's a trainer
        if (!creature->IsTrainer())
            continue;

        // Check if it's a valid trainer for this player
        if (!creature->IsValidTrainerForPlayer(bot))
            continue;

        // Check if it's a class trainer (not profession trainer)
        CreatureTemplate const* cTemplate = creature->GetCreatureTemplate();
        if (!cTemplate || cTemplate->trainer_type != TRAINER_TYPE_CLASS)
            continue;

        // Check if trainer spells are available
        TrainerSpellData const* trainer_spells = creature->GetTrainerSpells();
        if (!trainer_spells)
            continue;

        return creature;
    }

    return nullptr;
}

bool RespecAtTrainerAction::CanAffordRespec(uint32 cost) const
{
    return bot->GetMoney() >= cost;
}

bool RespecAtTrainerAction::DoRespec(Creature* trainer, uint8 targetSpecTab)
{
    // Get current spec tab
    uint8 currentTab = AiFactory::GetPlayerSpecTab(bot);
    if (currentTab == targetSpecTab)
    {
        botAI->TellMaster("Already in the desired spec");
        return false;
    }

    uint32 cost = GetRespecCost();

    // Deduct the cost
    if (cost > 0)
    {
        bot->ModifyMoney(-static_cast<int32>(cost));
    }

    // Reset talents
    bot->resetTalents(true);

    // Apply new talents using PlayerbotFactory
    PlayerbotFactory factory(bot, bot->GetLevel());
    PlayerbotFactory::InitTalentsBySpecNo(bot, targetSpecTab, false);

    // Update gear for new role
    GearRole newRole = AiFactory::GetCurrentGearRole(bot);
    if (sPlayerbotAIConfig->autoGearForRole)
    {
        factory.InitEquipmentForRole(newRole, true, false);
    }

    std::ostringstream out;
    out << "Respecced to " << AiFactory::GetPlayerSpecName(bot);
    out << " (cost: " << (cost / 10000) << "g)";
    botAI->TellMaster(out.str());

    return true;
}

uint32 RespecAtTrainerAction::GetRespecCost() const
{
    // WoW Classic respec cost formula:
    // 1g first time, increases by 5g each time, caps at 50g
    // Decays by 5g per month of real time (simplified here)

    // For simplicity, we use a fixed formula based on level and number of respecs
    // The actual respec count would need to be tracked per character

    uint32 respecCount = 0; // Would need to be stored somewhere

    const uint32 BASE_COST = 10000;      // 1 gold in copper
    const uint32 INCREMENT = 50000;       // 5 gold increment
    const uint32 MAX_COST = 500000;       // 50 gold cap

    uint32 cost = BASE_COST + (respecCount * INCREMENT);
    return std::min(cost, MAX_COST);
}

// EvaluateRoleSwitchAction implementation

bool EvaluateRoleSwitchAction::Execute(Event event)
{
    if (!ShouldSwitchRole())
        return false;

    GearRole desiredRole = AiFactory::GetDesiredGearRole(bot);
    GearRole currentRole = AiFactory::GetCurrentGearRole(bot);

    if (desiredRole == currentRole)
        return false;

    // Log the role switch recommendation
    std::ostringstream out;
    out << "Role switch recommended: ";

    switch (desiredRole)
    {
        case GearRole::ROLE_TANK:
            out << "Tank";
            break;
        case GearRole::ROLE_HEALER:
            out << "Healer";
            break;
        case GearRole::ROLE_MELEE_DPS:
            out << "Melee DPS";
            break;
        case GearRole::ROLE_RANGED_DPS:
            out << "Ranged DPS";
            break;
        case GearRole::ROLE_CASTER_DPS:
            out << "Caster DPS";
            break;
        default:
            out << "Unknown";
            break;
    }

    botAI->TellMaster(out.str());

    // The actual respec will happen when the bot is near a class trainer
    // and the RespecAtTrainerAction is executed

    return true;
}

bool EvaluateRoleSwitchAction::isUseful()
{
    // Only evaluate if dynamic role switching is enabled
    if (!sPlayerbotAIConfig->dynamicRoleSwitchingEnabled)
        return false;

    // Only evaluate if group role analysis is enabled
    if (!sPlayerbotAIConfig->groupRoleAnalysisEnabled)
        return false;

    // Only evaluate for bots above minimum level
    if (bot->GetLevel() < sPlayerbotAIConfig->roleSwitchMinLevel)
        return false;

    return true;
}

bool EvaluateRoleSwitchAction::ShouldSwitchRole() const
{
    // Check if we're in a group
    Group* group = bot->GetGroup();
    if (!group)
        return false;

    GearRole desiredRole = AiFactory::GetDesiredGearRole(bot, group);
    GearRole currentRole = AiFactory::GetCurrentGearRole(bot);

    // Check if the class can fulfill the desired role
    uint8 playerClass = bot->getClass();
    switch (desiredRole)
    {
        case GearRole::ROLE_TANK:
            if (!sRoleStatWeights->CanClassTank(playerClass))
                return false;
            break;
        case GearRole::ROLE_HEALER:
            if (!sRoleStatWeights->CanClassHeal(playerClass))
                return false;
            break;
        default:
            break;
    }

    return desiredRole != currentRole;
}
