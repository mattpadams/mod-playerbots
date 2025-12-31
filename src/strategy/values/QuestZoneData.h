/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_QUESTZONEDATA_H
#define _PLAYERBOT_QUESTZONEDATA_H

#include "Common.h"
#include <unordered_map>
#include <vector>

// Faction masks for zone accessibility
enum ZoneFactionMask : uint32
{
    ZONE_FACTION_NEUTRAL  = 0,
    ZONE_FACTION_ALLIANCE = 1,
    ZONE_FACTION_HORDE    = 2,
    ZONE_FACTION_BOTH     = 3
};

// Zone progression data for Classic (1-60)
struct ZoneProgressionInfo
{
    uint32 zoneId;
    uint8 minLevel;
    uint8 maxLevel;
    uint32 factionMask;
    std::vector<uint32> adjacentZones;
    std::vector<uint32> leadToZones;  // Natural progression zones
};

class QuestZoneData
{
public:
    static QuestZoneData* instance()
    {
        static QuestZoneData instance;
        return &instance;
    }

    const ZoneProgressionInfo* GetZoneInfo(uint32 zoneId) const;
    std::vector<uint32> GetRecommendedZones(uint8 level, uint32 factionMask) const;
    bool AreZonesAdjacent(uint32 zone1, uint32 zone2) const;
    float GetZoneFlowScore(uint32 currentZone, uint32 questZone, uint8 level) const;

private:
    QuestZoneData();
    void InitializeZoneData();

    std::unordered_map<uint32, ZoneProgressionInfo> zoneData;
};

#define sQuestZoneData QuestZoneData::instance()

#endif
