/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "StatsAction.h"

#include <map>
#include <vector>

#include "ChatHelper.h"
#include "Event.h"
#include "Playerbots.h"

bool StatsAction::Execute(Event event)
{
    std::ostringstream out;

    ListGold(out);

    out << ", ";
    ListBagSlots(out);

    out << ", ";
    ListRepairCost(out);

    if (bot->GetUInt32Value(PLAYER_NEXT_LEVEL_XP))
    {
        out << ", ";
        ListXP(out);
    }

    botAI->TellMaster(out);

    // List professions on a separate line
    std::ostringstream profOut;
    ListProfessions(profOut);
    if (!profOut.str().empty())
    {
        botAI->TellMaster(profOut);
    }

    // List available class quests
    ListClassQuests();

    // List trainable spells
    ListTrainableSpells();

    return true;
}

void StatsAction::ListGold(std::ostringstream& out) { out << chat->formatMoney(bot->GetMoney()); }

void StatsAction::ListBagSlots(std::ostringstream& out)
{
    uint32 totalused = 0, total = 16;

    // list out items in main backpack
    for (uint8 slot = INVENTORY_SLOT_ITEM_START; slot < INVENTORY_SLOT_ITEM_END; slot++)
    {
        if (bot->GetItemByPos(INVENTORY_SLOT_BAG_0, slot))
        {
            ++totalused;
        }
    }

    uint32 totalfree = 16 - totalused;

    // list out items in other removable backpacks
    for (uint8 bag = INVENTORY_SLOT_BAG_START; bag < INVENTORY_SLOT_BAG_END; ++bag)
    {
        if (Bag const* pBag = (Bag*)bot->GetItemByPos(INVENTORY_SLOT_BAG_0, bag))
        {
            ItemTemplate const* pBagProto = pBag->GetTemplate();
            if (pBagProto->Class == ITEM_CLASS_CONTAINER && pBagProto->SubClass == ITEM_SUBCLASS_CONTAINER)
            {
                total += pBag->GetBagSize();
                totalfree += pBag->GetFreeSlots();
            }
        }
    }

    std::string color = "ff00ff00";
    if (totalfree < total / 2)
        color = "ffffff00";

    if (totalfree < total / 4)
        color = "ffff0000";

    out << "|h|c" << color << totalfree << "/" << total << "|h|cffffffff Bag";
}

void StatsAction::ListXP(std::ostringstream& out)
{
    uint32 curXP = bot->GetUInt32Value(PLAYER_XP);
    uint32 nextLevelXP = bot->GetUInt32Value(PLAYER_NEXT_LEVEL_XP);
    uint32 restXP = bot->GetUInt32Value(PLAYER_REST_STATE_EXPERIENCE);
    uint32 xpPercent = 0;

    if (nextLevelXP)
        xpPercent = 100 * curXP / nextLevelXP;

    uint32 restPercent = 0;
    if (restXP && nextLevelXP)
        restPercent = 2 * (100 * restXP / nextLevelXP);

    out << "|cff00ff00" << xpPercent << "|cffffd333/|cff00ff00" << restPercent << "%|cffffffff XP";
}

void StatsAction::ListRepairCost(std::ostringstream& out)
{
    uint32 totalCost = 0;
    double repairPercent = 0;
    double repairCount = 0;

    for (uint32 i = EQUIPMENT_SLOT_START; i < INVENTORY_SLOT_ITEM_END; ++i)
    {
        uint16 pos = ((INVENTORY_SLOT_BAG_0 << 8) | i);
        totalCost += EstRepair(pos);
        double repair = RepairPercent(pos);
        if (repair < 100)
        {
            repairPercent += repair;
            ++repairCount;
        }
    }

    repairPercent /= repairCount;

    std::string color = "ff00ff00";
    if (repairPercent < 50)
        color = "ffffff00";

    if (repairPercent < 25)
        color = "ffff0000";

    out << "|c" << color << (uint32)ceil(repairPercent) << "% (" << chat->formatMoney(totalCost) << ")|cffffffff Dur";
}

uint32 StatsAction::EstRepair(uint16 pos)
{
    Item* item = bot->GetItemByPos(pos);

    uint32 TotalCost = 0;
    if (!item)
        return TotalCost;

    uint32 maxDurability = item->GetUInt32Value(ITEM_FIELD_MAXDURABILITY);
    if (!maxDurability)
        return TotalCost;

    uint32 curDurability = item->GetUInt32Value(ITEM_FIELD_DURABILITY);

    uint32 LostDurability = maxDurability - curDurability;
    if (LostDurability > 0)
    {
        ItemTemplate const* ditemProto = item->GetTemplate();

        DurabilityCostsEntry const* dcost = sDurabilityCostsStore.LookupEntry(ditemProto->ItemLevel);
        if (!dcost)
        {
            LOG_ERROR("playerbots", "RepairDurability: Wrong item lvl {}", ditemProto->ItemLevel);
            return TotalCost;
        }

        uint32 dQualitymodEntryId = (ditemProto->Quality + 1) * 2;
        DurabilityQualityEntry const* dQualitymodEntry = sDurabilityQualityStore.LookupEntry(dQualitymodEntryId);
        if (!dQualitymodEntry)
        {
            LOG_ERROR("playerbots", "RepairDurability: Wrong dQualityModEntry {}", dQualitymodEntryId);
            return TotalCost;
        }

        uint32 dmultiplier =
            dcost->multiplier[ItemSubClassToDurabilityMultiplierId(ditemProto->Class, ditemProto->SubClass)];
        uint32 costs = uint32(LostDurability * dmultiplier * double(dQualitymodEntry->quality_mod));

        if (!costs)  // fix for ITEM_QUALITY_ARTIFACT
            costs = 1;

        TotalCost = costs;
    }

    return TotalCost;
}

double StatsAction::RepairPercent(uint16 pos)
{
    Item* item = bot->GetItemByPos(pos);
    if (!item)
        return 100;

    uint32 maxDurability = item->GetUInt32Value(ITEM_FIELD_MAXDURABILITY);
    if (!maxDurability)
        return 100;

    uint32 curDurability = item->GetUInt32Value(ITEM_FIELD_DURABILITY);
    if (!curDurability)
        return 0;

    return curDurability * 100.0 / maxDurability;
}

void StatsAction::ListProfessions(std::ostringstream& out)
{
    // Primary professions
    std::map<uint32, std::string> primarySkills = {
        {SKILL_ALCHEMY, "Alch"},
        {SKILL_BLACKSMITHING, "BS"},
        {SKILL_ENCHANTING, "Ench"},
        {SKILL_ENGINEERING, "Eng"},
        {SKILL_HERBALISM, "Herb"},
        {SKILL_JEWELCRAFTING, "JC"},
        {SKILL_LEATHERWORKING, "LW"},
        {SKILL_MINING, "Mine"},
        {SKILL_SKINNING, "Skin"},
        {SKILL_TAILORING, "Tail"},
        {SKILL_INSCRIPTION, "Insc"}
    };

    // Secondary professions
    std::map<uint32, std::string> secondarySkills = {
        {SKILL_COOKING, "Cook"},
        {SKILL_FIRST_AID, "FA"},
        {SKILL_FISHING, "Fish"}
    };

    bool first = true;

    // List primary professions
    for (auto const& skill : primarySkills)
    {
        if (bot->HasSkill(skill.first))
        {
            uint32 value = bot->GetSkillValue(skill.first);
            uint32 maxValue = bot->GetMaxSkillValue(skill.first);
            if (value > 0)
            {
                if (!first)
                    out << ", ";
                out << "|cff00ff00" << skill.second << "|cffffffff " << value << "/" << maxValue;
                first = false;
            }
        }
    }

    // List secondary professions
    for (auto const& skill : secondarySkills)
    {
        if (bot->HasSkill(skill.first))
        {
            uint32 value = bot->GetSkillValue(skill.first);
            uint32 maxValue = bot->GetMaxSkillValue(skill.first);
            if (value > 0)
            {
                if (!first)
                    out << ", ";
                out << "|cff00ff00" << skill.second << "|cffffffff " << value << "/" << maxValue;
                first = false;
            }
        }
    }
}

void StatsAction::ListClassQuests()
{
    std::vector<std::pair<Quest const*, uint32>> availableQuests;

    ObjectMgr::QuestMap const& questTemplates = sObjectMgr->GetQuestTemplates();
    for (auto const& questPair : questTemplates)
    {
        Quest const* quest = questPair.second;

        // Only class-specific quests that reward spells
        if (!quest->GetRequiredClasses() || quest->IsRepeatable() || quest->GetMinLevel() < 10)
            continue;

        // Must have a spell reward
        if (quest->GetRewSpellCast() <= 0 && quest->GetRewSpell() <= 0)
            continue;

        // Check if bot can do this quest
        if (!bot->SatisfyQuestClass(quest, false) ||
            quest->GetMinLevel() > bot->GetLevel() ||
            !bot->SatisfyQuestRace(quest, false))
            continue;

        // Check if already completed or in progress
        if (bot->GetQuestStatus(questPair.first) == QUEST_STATUS_REWARDED ||
            bot->GetQuestStatus(questPair.first) == QUEST_STATUS_COMPLETE ||
            bot->GetQuestStatus(questPair.first) == QUEST_STATUS_INCOMPLETE)
            continue;

        // Check if bot already has the spell
        uint32 spellId = quest->GetRewSpellCast() > 0 ? quest->GetRewSpellCast() : quest->GetRewSpell();
        SpellInfo const* spellInfo = sSpellMgr->GetSpellInfo(spellId);
        if (!spellInfo)
            continue;

        bool hasSpell = false;
        for (uint8 j = 0; j < 3; ++j)
        {
            if (spellInfo->Effects[j].Effect == SPELL_EFFECT_LEARN_SPELL)
            {
                if (bot->HasSpell(spellInfo->Effects[j].TriggerSpell))
                {
                    hasSpell = true;
                    break;
                }
            }
        }
        if (!hasSpell && bot->HasSpell(spellId))
            hasSpell = true;

        if (!hasSpell)
            availableQuests.push_back({quest, spellId});
    }

    if (!availableQuests.empty())
    {
        std::ostringstream out;
        out << "|cffff6600Class quests available:|cffffffff";
        botAI->TellMaster(out);

        for (auto const& questData : availableQuests)
        {
            Quest const* quest = questData.first;
            uint32 spellId = questData.second;
            SpellInfo const* spellInfo = sSpellMgr->GetSpellInfo(spellId);

            std::ostringstream questOut;
            questOut << "  |cff00ff00[" << quest->GetTitle() << "]|cffffffff (Lv" << quest->GetMinLevel() << ")";

            // Add spell name that will be learned
            if (spellInfo)
            {
                // Check if this spell teaches another spell
                for (uint8 j = 0; j < 3; ++j)
                {
                    if (spellInfo->Effects[j].Effect == SPELL_EFFECT_LEARN_SPELL)
                    {
                        SpellInfo const* learnedSpell = sSpellMgr->GetSpellInfo(spellInfo->Effects[j].TriggerSpell);
                        if (learnedSpell)
                        {
                            questOut << " -> " << learnedSpell->SpellName[0];
                            break;
                        }
                    }
                }
                if (questOut.str().find("->") == std::string::npos)
                {
                    questOut << " -> " << spellInfo->SpellName[0];
                }
            }

            botAI->TellMaster(questOut);
        }
    }
}

void StatsAction::ListTrainableSpells()
{
    uint8 botClass = bot->getClass();
    std::vector<std::pair<std::string, uint32>> trainableSpells;

    // Iterate through creature templates to find class trainers
    for (auto const& trainerPair : *sObjectMgr->GetCreatureTemplates())
    {
        CreatureTemplate const& creatureTemplate = trainerPair.second;

        // Check if this is a class trainer for the bot's class
        if (creatureTemplate.trainer_type != TRAINER_TYPE_CLASS)
            continue;

        if (creatureTemplate.trainer_class != botClass)
            continue;

        // Get trainer spells directly from ObjectMgr
        TrainerSpellData const* trainerSpells = sObjectMgr->GetNpcTrainerSpells(trainerPair.first);
        if (!trainerSpells)
            continue;

        for (auto const& spellPair : trainerSpells->spellList)
        {
            TrainerSpell const& tSpell = spellPair.second;

            // Check if bot can learn this spell
            TrainerSpellState state = bot->GetTrainerSpellState(&tSpell);
            if (state != TRAINER_SPELL_GREEN)
                continue;

            SpellInfo const* spellInfo = sSpellMgr->GetSpellInfo(tSpell.spell);
            if (!spellInfo)
                continue;

            // Check if bot already has this spell
            bool hasSpell = false;
            std::string spellName;
            uint32 cost = tSpell.spellCost;

            for (uint8 j = 0; j < 3; ++j)
            {
                if (spellInfo->Effects[j].Effect == SPELL_EFFECT_LEARN_SPELL)
                {
                    uint32 learnedSpellId = spellInfo->Effects[j].TriggerSpell;
                    if (bot->HasSpell(learnedSpellId))
                    {
                        hasSpell = true;
                        break;
                    }
                    SpellInfo const* learnedSpell = sSpellMgr->GetSpellInfo(learnedSpellId);
                    if (learnedSpell)
                    {
                        spellName = learnedSpell->SpellName[0];
                        if (learnedSpell->Rank[0][0])
                        {
                            spellName += " ";
                            spellName += learnedSpell->Rank[0];
                        }
                    }
                }
            }

            if (!hasSpell && bot->HasSpell(tSpell.spell))
                hasSpell = true;

            if (spellName.empty())
            {
                spellName = spellInfo->SpellName[0];
                if (spellInfo->Rank[0][0])
                {
                    spellName += " ";
                    spellName += spellInfo->Rank[0];
                }
            }

            if (!hasSpell)
                trainableSpells.push_back({spellName, cost});
        }

        // Found a valid trainer, no need to check more
        break;
    }

    if (!trainableSpells.empty())
    {
        std::ostringstream out;
        out << "|cffff6600" << trainableSpells.size() << " spell" << (trainableSpells.size() > 1 ? "s" : "") << " to train:|cffffffff";
        botAI->TellMaster(out);

        // Show up to 5 spells
        uint32 shown = 0;
        for (auto const& spell : trainableSpells)
        {
            if (shown >= 5)
            {
                std::ostringstream moreOut;
                moreOut << "  ... and " << (trainableSpells.size() - 5) << " more";
                botAI->TellMaster(moreOut);
                break;
            }

            std::ostringstream spellOut;
            spellOut << "  |cff71d5ff" << spell.first << "|cffffffff (" << chat->formatMoney(spell.second) << ")";
            botAI->TellMaster(spellOut);
            ++shown;
        }
    }
}
