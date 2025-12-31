/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "QuestZoneData.h"

// Classic WoW Zone IDs
enum ClassicZoneIds : uint32
{
    // Eastern Kingdoms - Alliance Starting Zones
    ZONE_DUN_MOROGH         = 1,
    ZONE_ELWYNN_FOREST      = 12,

    // Eastern Kingdoms - Horde Starting Zones
    ZONE_TIRISFAL_GLADES    = 85,

    // Eastern Kingdoms - Low Level (10-20)
    ZONE_LOCH_MODAN         = 38,
    ZONE_WESTFALL           = 40,
    ZONE_DARKSHORE          = 148,
    ZONE_SILVERPINE_FOREST  = 130,
    ZONE_REDRIDGE_MOUNTAINS = 44,

    // Eastern Kingdoms - Mid Level (20-30)
    ZONE_WETLANDS           = 11,
    ZONE_DUSKWOOD           = 10,
    ZONE_HILLSBRAD_FOOTHILLS = 267,

    // Eastern Kingdoms - Higher Level (30-45)
    ZONE_STRANGLETHORN_VALE = 33,
    ZONE_ARATHI_HIGHLANDS   = 45,
    ZONE_HINTERLANDS        = 47,
    ZONE_BADLANDS           = 3,
    ZONE_SWAMP_OF_SORROWS   = 8,
    ZONE_SEARING_GORGE      = 51,

    // Eastern Kingdoms - High Level (45-60)
    ZONE_BLASTED_LANDS      = 4,
    ZONE_BURNING_STEPPES    = 46,
    ZONE_WESTERN_PLAGUELANDS = 28,
    ZONE_EASTERN_PLAGUELANDS = 139,
    ZONE_DEADWIND_PASS      = 41,

    // Kalimdor - Alliance Starting Zones
    ZONE_TELDRASSIL         = 141,

    // Kalimdor - Horde Starting Zones
    ZONE_DUROTAR            = 14,
    ZONE_MULGORE            = 215,

    // Kalimdor - Low Level (10-20)
    ZONE_BARRENS            = 17,
    ZONE_STONETALON_MOUNTAINS = 406,

    // Kalimdor - Mid Level (20-35)
    ZONE_ASHENVALE          = 331,
    ZONE_THOUSAND_NEEDLES   = 400,
    ZONE_DESOLACE           = 405,

    // Kalimdor - Higher Level (35-50)
    ZONE_DUSTWALLOW_MARSH   = 15,
    ZONE_FERALAS            = 357,
    ZONE_TANARIS            = 440,

    // Kalimdor - High Level (45-60)
    ZONE_AZSHARA            = 16,
    ZONE_FELWOOD            = 361,
    ZONE_UN_GORO_CRATER     = 490,
    ZONE_WINTERSPRING       = 618,
    ZONE_SILITHUS           = 1377
};

QuestZoneData::QuestZoneData()
{
    InitializeZoneData();
}

void QuestZoneData::InitializeZoneData()
{
    // ==================== ALLIANCE STARTING ZONES ====================

    // Elwynn Forest (Human starting)
    zoneData[ZONE_ELWYNN_FOREST] = {
        ZONE_ELWYNN_FOREST, 1, 10, ZONE_FACTION_ALLIANCE,
        {ZONE_WESTFALL, ZONE_REDRIDGE_MOUNTAINS, ZONE_DUSKWOOD},
        {ZONE_WESTFALL, ZONE_REDRIDGE_MOUNTAINS}
    };

    // Dun Morogh (Dwarf/Gnome starting)
    zoneData[ZONE_DUN_MOROGH] = {
        ZONE_DUN_MOROGH, 1, 10, ZONE_FACTION_ALLIANCE,
        {ZONE_LOCH_MODAN},
        {ZONE_LOCH_MODAN}
    };

    // Teldrassil (Night Elf starting)
    zoneData[ZONE_TELDRASSIL] = {
        ZONE_TELDRASSIL, 1, 10, ZONE_FACTION_ALLIANCE,
        {ZONE_DARKSHORE},
        {ZONE_DARKSHORE}
    };

    // ==================== HORDE STARTING ZONES ====================

    // Durotar (Orc/Troll starting)
    zoneData[ZONE_DUROTAR] = {
        ZONE_DUROTAR, 1, 10, ZONE_FACTION_HORDE,
        {ZONE_BARRENS},
        {ZONE_BARRENS}
    };

    // Mulgore (Tauren starting)
    zoneData[ZONE_MULGORE] = {
        ZONE_MULGORE, 1, 10, ZONE_FACTION_HORDE,
        {ZONE_BARRENS},
        {ZONE_BARRENS}
    };

    // Tirisfal Glades (Undead starting)
    zoneData[ZONE_TIRISFAL_GLADES] = {
        ZONE_TIRISFAL_GLADES, 1, 10, ZONE_FACTION_HORDE,
        {ZONE_SILVERPINE_FOREST},
        {ZONE_SILVERPINE_FOREST}
    };

    // ==================== LOW LEVEL ZONES (10-20) ====================

    // Westfall (Alliance)
    zoneData[ZONE_WESTFALL] = {
        ZONE_WESTFALL, 10, 18, ZONE_FACTION_ALLIANCE,
        {ZONE_ELWYNN_FOREST, ZONE_DUSKWOOD, ZONE_STRANGLETHORN_VALE},
        {ZONE_DUSKWOOD, ZONE_REDRIDGE_MOUNTAINS}
    };

    // Loch Modan (Alliance)
    zoneData[ZONE_LOCH_MODAN] = {
        ZONE_LOCH_MODAN, 10, 18, ZONE_FACTION_ALLIANCE,
        {ZONE_DUN_MOROGH, ZONE_WETLANDS, ZONE_BADLANDS},
        {ZONE_WETLANDS}
    };

    // Darkshore (Alliance)
    zoneData[ZONE_DARKSHORE] = {
        ZONE_DARKSHORE, 10, 20, ZONE_FACTION_ALLIANCE,
        {ZONE_TELDRASSIL, ZONE_ASHENVALE},
        {ZONE_ASHENVALE}
    };

    // Redridge Mountains (Alliance)
    zoneData[ZONE_REDRIDGE_MOUNTAINS] = {
        ZONE_REDRIDGE_MOUNTAINS, 15, 25, ZONE_FACTION_ALLIANCE,
        {ZONE_ELWYNN_FOREST, ZONE_DUSKWOOD, ZONE_BURNING_STEPPES},
        {ZONE_DUSKWOOD}
    };

    // Silverpine Forest (Horde)
    zoneData[ZONE_SILVERPINE_FOREST] = {
        ZONE_SILVERPINE_FOREST, 10, 20, ZONE_FACTION_HORDE,
        {ZONE_TIRISFAL_GLADES, ZONE_HILLSBRAD_FOOTHILLS},
        {ZONE_HILLSBRAD_FOOTHILLS}
    };

    // The Barrens (Horde)
    zoneData[ZONE_BARRENS] = {
        ZONE_BARRENS, 10, 25, ZONE_FACTION_HORDE,
        {ZONE_DUROTAR, ZONE_MULGORE, ZONE_ASHENVALE, ZONE_STONETALON_MOUNTAINS, ZONE_THOUSAND_NEEDLES, ZONE_DUSTWALLOW_MARSH},
        {ZONE_ASHENVALE, ZONE_STONETALON_MOUNTAINS, ZONE_THOUSAND_NEEDLES}
    };

    // ==================== MID LEVEL ZONES (20-35) ====================

    // Duskwood (Alliance)
    zoneData[ZONE_DUSKWOOD] = {
        ZONE_DUSKWOOD, 18, 30, ZONE_FACTION_ALLIANCE,
        {ZONE_ELWYNN_FOREST, ZONE_WESTFALL, ZONE_REDRIDGE_MOUNTAINS, ZONE_STRANGLETHORN_VALE, ZONE_DEADWIND_PASS},
        {ZONE_STRANGLETHORN_VALE}
    };

    // Wetlands (Alliance)
    zoneData[ZONE_WETLANDS] = {
        ZONE_WETLANDS, 20, 30, ZONE_FACTION_ALLIANCE,
        {ZONE_LOCH_MODAN, ZONE_ARATHI_HIGHLANDS},
        {ZONE_ARATHI_HIGHLANDS}
    };

    // Hillsbrad Foothills (Neutral/Horde favored)
    zoneData[ZONE_HILLSBRAD_FOOTHILLS] = {
        ZONE_HILLSBRAD_FOOTHILLS, 20, 30, ZONE_FACTION_BOTH,
        {ZONE_SILVERPINE_FOREST, ZONE_ARATHI_HIGHLANDS, ZONE_HINTERLANDS},
        {ZONE_ARATHI_HIGHLANDS}
    };

    // Ashenvale (Neutral)
    zoneData[ZONE_ASHENVALE] = {
        ZONE_ASHENVALE, 18, 30, ZONE_FACTION_BOTH,
        {ZONE_DARKSHORE, ZONE_BARRENS, ZONE_STONETALON_MOUNTAINS, ZONE_FELWOOD, ZONE_AZSHARA},
        {ZONE_STONETALON_MOUNTAINS, ZONE_FELWOOD}
    };

    // Stonetalon Mountains (Neutral)
    zoneData[ZONE_STONETALON_MOUNTAINS] = {
        ZONE_STONETALON_MOUNTAINS, 15, 27, ZONE_FACTION_BOTH,
        {ZONE_ASHENVALE, ZONE_BARRENS, ZONE_DESOLACE},
        {ZONE_DESOLACE}
    };

    // Thousand Needles (Neutral)
    zoneData[ZONE_THOUSAND_NEEDLES] = {
        ZONE_THOUSAND_NEEDLES, 25, 35, ZONE_FACTION_BOTH,
        {ZONE_BARRENS, ZONE_FERALAS, ZONE_TANARIS},
        {ZONE_TANARIS, ZONE_FERALAS}
    };

    // Desolace (Neutral)
    zoneData[ZONE_DESOLACE] = {
        ZONE_DESOLACE, 30, 40, ZONE_FACTION_BOTH,
        {ZONE_STONETALON_MOUNTAINS, ZONE_FERALAS},
        {ZONE_FERALAS}
    };

    // ==================== MID-HIGH LEVEL ZONES (30-45) ====================

    // Stranglethorn Vale (Neutral)
    zoneData[ZONE_STRANGLETHORN_VALE] = {
        ZONE_STRANGLETHORN_VALE, 30, 45, ZONE_FACTION_BOTH,
        {ZONE_WESTFALL, ZONE_DUSKWOOD, ZONE_SWAMP_OF_SORROWS, ZONE_BLASTED_LANDS},
        {ZONE_SWAMP_OF_SORROWS, ZONE_BLASTED_LANDS}
    };

    // Arathi Highlands (Neutral)
    zoneData[ZONE_ARATHI_HIGHLANDS] = {
        ZONE_ARATHI_HIGHLANDS, 30, 40, ZONE_FACTION_BOTH,
        {ZONE_WETLANDS, ZONE_HILLSBRAD_FOOTHILLS, ZONE_HINTERLANDS},
        {ZONE_HINTERLANDS}
    };

    // Hinterlands (Neutral)
    zoneData[ZONE_HINTERLANDS] = {
        ZONE_HINTERLANDS, 40, 50, ZONE_FACTION_BOTH,
        {ZONE_ARATHI_HIGHLANDS, ZONE_HILLSBRAD_FOOTHILLS, ZONE_WESTERN_PLAGUELANDS},
        {ZONE_WESTERN_PLAGUELANDS}
    };

    // Badlands (Neutral)
    zoneData[ZONE_BADLANDS] = {
        ZONE_BADLANDS, 35, 45, ZONE_FACTION_BOTH,
        {ZONE_LOCH_MODAN, ZONE_SEARING_GORGE},
        {ZONE_SEARING_GORGE}
    };

    // Swamp of Sorrows (Neutral)
    zoneData[ZONE_SWAMP_OF_SORROWS] = {
        ZONE_SWAMP_OF_SORROWS, 35, 45, ZONE_FACTION_BOTH,
        {ZONE_STRANGLETHORN_VALE, ZONE_BLASTED_LANDS, ZONE_DEADWIND_PASS},
        {ZONE_BLASTED_LANDS}
    };

    // Dustwallow Marsh (Neutral)
    zoneData[ZONE_DUSTWALLOW_MARSH] = {
        ZONE_DUSTWALLOW_MARSH, 35, 45, ZONE_FACTION_BOTH,
        {ZONE_BARRENS},
        {ZONE_TANARIS}
    };

    // Feralas (Neutral)
    zoneData[ZONE_FERALAS] = {
        ZONE_FERALAS, 40, 50, ZONE_FACTION_BOTH,
        {ZONE_THOUSAND_NEEDLES, ZONE_DESOLACE},
        {ZONE_UN_GORO_CRATER}
    };

    // Tanaris (Neutral)
    zoneData[ZONE_TANARIS] = {
        ZONE_TANARIS, 40, 50, ZONE_FACTION_BOTH,
        {ZONE_THOUSAND_NEEDLES, ZONE_UN_GORO_CRATER, ZONE_SILITHUS},
        {ZONE_UN_GORO_CRATER}
    };

    // ==================== HIGH LEVEL ZONES (45-60) ====================

    // Searing Gorge (Neutral)
    zoneData[ZONE_SEARING_GORGE] = {
        ZONE_SEARING_GORGE, 43, 50, ZONE_FACTION_BOTH,
        {ZONE_BADLANDS, ZONE_BURNING_STEPPES},
        {ZONE_BURNING_STEPPES}
    };

    // Blasted Lands (Neutral)
    zoneData[ZONE_BLASTED_LANDS] = {
        ZONE_BLASTED_LANDS, 45, 55, ZONE_FACTION_BOTH,
        {ZONE_STRANGLETHORN_VALE, ZONE_SWAMP_OF_SORROWS},
        {}
    };

    // Burning Steppes (Neutral)
    zoneData[ZONE_BURNING_STEPPES] = {
        ZONE_BURNING_STEPPES, 50, 58, ZONE_FACTION_BOTH,
        {ZONE_REDRIDGE_MOUNTAINS, ZONE_SEARING_GORGE},
        {}
    };

    // Felwood (Neutral)
    zoneData[ZONE_FELWOOD] = {
        ZONE_FELWOOD, 48, 55, ZONE_FACTION_BOTH,
        {ZONE_ASHENVALE, ZONE_WINTERSPRING},
        {ZONE_WINTERSPRING}
    };

    // Azshara (Neutral)
    zoneData[ZONE_AZSHARA] = {
        ZONE_AZSHARA, 45, 55, ZONE_FACTION_BOTH,
        {ZONE_ASHENVALE},
        {}
    };

    // Un'Goro Crater (Neutral)
    zoneData[ZONE_UN_GORO_CRATER] = {
        ZONE_UN_GORO_CRATER, 48, 55, ZONE_FACTION_BOTH,
        {ZONE_TANARIS, ZONE_SILITHUS},
        {ZONE_SILITHUS}
    };

    // Western Plaguelands (Neutral)
    zoneData[ZONE_WESTERN_PLAGUELANDS] = {
        ZONE_WESTERN_PLAGUELANDS, 51, 58, ZONE_FACTION_BOTH,
        {ZONE_HINTERLANDS, ZONE_TIRISFAL_GLADES, ZONE_EASTERN_PLAGUELANDS},
        {ZONE_EASTERN_PLAGUELANDS}
    };

    // Eastern Plaguelands (Neutral)
    zoneData[ZONE_EASTERN_PLAGUELANDS] = {
        ZONE_EASTERN_PLAGUELANDS, 53, 60, ZONE_FACTION_BOTH,
        {ZONE_WESTERN_PLAGUELANDS},
        {}
    };

    // Winterspring (Neutral)
    zoneData[ZONE_WINTERSPRING] = {
        ZONE_WINTERSPRING, 53, 60, ZONE_FACTION_BOTH,
        {ZONE_FELWOOD},
        {}
    };

    // Silithus (Neutral)
    zoneData[ZONE_SILITHUS] = {
        ZONE_SILITHUS, 55, 60, ZONE_FACTION_BOTH,
        {ZONE_UN_GORO_CRATER, ZONE_TANARIS},
        {}
    };

    // Deadwind Pass (Neutral - mainly a travel zone)
    zoneData[ZONE_DEADWIND_PASS] = {
        ZONE_DEADWIND_PASS, 55, 60, ZONE_FACTION_BOTH,
        {ZONE_DUSKWOOD, ZONE_SWAMP_OF_SORROWS},
        {}
    };
}

const ZoneProgressionInfo* QuestZoneData::GetZoneInfo(uint32 zoneId) const
{
    auto it = zoneData.find(zoneId);
    if (it != zoneData.end())
        return &it->second;
    return nullptr;
}

std::vector<uint32> QuestZoneData::GetRecommendedZones(uint8 level, uint32 factionMask) const
{
    std::vector<uint32> recommended;

    for (const auto& pair : zoneData)
    {
        const ZoneProgressionInfo& info = pair.second;

        // Check level range
        if (level < info.minLevel || level > info.maxLevel + 3)
            continue;

        // Check faction
        if (info.factionMask != ZONE_FACTION_BOTH &&
            info.factionMask != ZONE_FACTION_NEUTRAL &&
            !(info.factionMask & factionMask))
            continue;

        recommended.push_back(info.zoneId);
    }

    return recommended;
}

bool QuestZoneData::AreZonesAdjacent(uint32 zone1, uint32 zone2) const
{
    const ZoneProgressionInfo* info = GetZoneInfo(zone1);
    if (!info)
        return false;

    for (uint32 adjZone : info->adjacentZones)
    {
        if (adjZone == zone2)
            return true;
    }

    return false;
}

float QuestZoneData::GetZoneFlowScore(uint32 currentZone, uint32 questZone, uint8 level) const
{
    // Same zone = best score
    if (currentZone == questZone)
        return 1.0f;

    const ZoneProgressionInfo* currentInfo = GetZoneInfo(currentZone);
    const ZoneProgressionInfo* questInfo = GetZoneInfo(questZone);

    if (!currentInfo || !questInfo)
        return 0.3f;

    // Adjacent zone = good score
    if (AreZonesAdjacent(currentZone, questZone))
        return 0.8f;

    // Natural progression zone = good score
    for (uint32 nextZone : currentInfo->leadToZones)
    {
        if (nextZone == questZone)
            return 0.75f;
    }

    // Check if quest zone is appropriate for level
    if (level >= questInfo->minLevel && level <= questInfo->maxLevel)
        return 0.5f;

    // Quest zone is too low or high level
    if (level > questInfo->maxLevel + 3)
        return 0.2f;

    if (level < questInfo->minLevel - 2)
        return 0.1f;

    return 0.3f;
}
