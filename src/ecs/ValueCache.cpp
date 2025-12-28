/*
 * ECS Value Cache Implementation
 *
 * Provides fast cached value lookups using spatial indexing
 * and ECS components instead of per-bot grid searches.
 */

#include "ValueCache.h"
#include "BotRegistry.h"
#include "Player.h"
#include "PlayerbotAI.h"
#include "PlayerbotAIConfig.h"
#include "Group.h"
#include "ObjectAccessor.h"
#include "ThreatMgr.h"
#include "Timer.h"
#include "Log.h"
#include <cmath>

namespace ecs {

// Static metrics
ValueCacheSystem::Metrics ValueCacheSystem::s_metrics;

// =============================================================================
// MapSpatialIndex Implementation
// =============================================================================

void MapSpatialIndex::UpdateUnit(uint64_t guid, float x, float y, bool isHostile, bool isFriendly)
{
    int32_t cellX = ToCellCoord(x);
    int32_t cellY = ToCellCoord(y);
    int64_t newCellKey = CellKey(cellX, cellY);

    // Check if unit needs to move cells
    auto it = m_unitCells.find(guid);
    if (it != m_unitCells.end())
    {
        if (it->second == newCellKey)
        {
            // Same cell, no update needed
            return;
        }

        // Remove from old cell
        int64_t oldCellKey = it->second;
        auto cellIt = m_cells.find(oldCellKey);
        if (cellIt != m_cells.end())
        {
            auto& cell = cellIt->second;
            auto guidIt = std::find(cell.unitGuids.begin(), cell.unitGuids.end(), guid);
            if (guidIt != cell.unitGuids.end())
                cell.unitGuids.erase(guidIt);

            auto hostileIt = std::find(cell.hostileGuids.begin(), cell.hostileGuids.end(), guid);
            if (hostileIt != cell.hostileGuids.end())
                cell.hostileGuids.erase(hostileIt);

            auto friendlyIt = std::find(cell.friendlyGuids.begin(), cell.friendlyGuids.end(), guid);
            if (friendlyIt != cell.friendlyGuids.end())
                cell.friendlyGuids.erase(friendlyIt);
        }
    }

    // Add to new cell
    SpatialCell& cell = m_cells[newCellKey];
    cell.unitGuids.push_back(guid);
    if (isHostile)
        cell.hostileGuids.push_back(guid);
    if (isFriendly)
        cell.friendlyGuids.push_back(guid);
    cell.lastUpdate = getMSTime();

    m_unitCells[guid] = newCellKey;
}

void MapSpatialIndex::RemoveUnit(uint64_t guid)
{
    auto it = m_unitCells.find(guid);
    if (it == m_unitCells.end())
        return;

    int64_t cellKey = it->second;
    auto cellIt = m_cells.find(cellKey);
    if (cellIt != m_cells.end())
    {
        auto& cell = cellIt->second;

        auto guidIt = std::find(cell.unitGuids.begin(), cell.unitGuids.end(), guid);
        if (guidIt != cell.unitGuids.end())
            cell.unitGuids.erase(guidIt);

        auto hostileIt = std::find(cell.hostileGuids.begin(), cell.hostileGuids.end(), guid);
        if (hostileIt != cell.hostileGuids.end())
            cell.hostileGuids.erase(hostileIt);

        auto friendlyIt = std::find(cell.friendlyGuids.begin(), cell.friendlyGuids.end(), guid);
        if (friendlyIt != cell.friendlyGuids.end())
            cell.friendlyGuids.erase(friendlyIt);
    }

    m_unitCells.erase(it);
}

std::vector<uint64_t> MapSpatialIndex::FindUnitsInRange(float x, float y, float radius) const
{
    std::vector<uint64_t> result;

    int32_t centerCellX = ToCellCoord(x);
    int32_t centerCellY = ToCellCoord(y);
    int32_t cellRadius = static_cast<int32_t>(std::ceil(radius / CELL_SIZE)) + 1;

    float radiusSq = radius * radius;

    for (int32_t dx = -cellRadius; dx <= cellRadius; ++dx)
    {
        for (int32_t dy = -cellRadius; dy <= cellRadius; ++dy)
        {
            int64_t cellKey = CellKey(centerCellX + dx, centerCellY + dy);
            auto it = m_cells.find(cellKey);
            if (it == m_cells.end())
                continue;

            // For units in this cell, we could do precise distance check
            // but for performance, we accept all units in nearby cells
            // The caller should do precise checks if needed
            for (uint64_t guid : it->second.unitGuids)
            {
                result.push_back(guid);
            }
        }
    }

    return result;
}

std::vector<uint64_t> MapSpatialIndex::FindHostilesInRange(float x, float y, float radius) const
{
    std::vector<uint64_t> result;

    int32_t centerCellX = ToCellCoord(x);
    int32_t centerCellY = ToCellCoord(y);
    int32_t cellRadius = static_cast<int32_t>(std::ceil(radius / CELL_SIZE)) + 1;

    for (int32_t dx = -cellRadius; dx <= cellRadius; ++dx)
    {
        for (int32_t dy = -cellRadius; dy <= cellRadius; ++dy)
        {
            int64_t cellKey = CellKey(centerCellX + dx, centerCellY + dy);
            auto it = m_cells.find(cellKey);
            if (it == m_cells.end())
                continue;

            for (uint64_t guid : it->second.hostileGuids)
            {
                result.push_back(guid);
            }
        }
    }

    return result;
}

std::vector<uint64_t> MapSpatialIndex::FindFriendliesInRange(float x, float y, float radius) const
{
    std::vector<uint64_t> result;

    int32_t centerCellX = ToCellCoord(x);
    int32_t centerCellY = ToCellCoord(y);
    int32_t cellRadius = static_cast<int32_t>(std::ceil(radius / CELL_SIZE)) + 1;

    for (int32_t dx = -cellRadius; dx <= cellRadius; ++dx)
    {
        for (int32_t dy = -cellRadius; dy <= cellRadius; ++dy)
        {
            int64_t cellKey = CellKey(centerCellX + dx, centerCellY + dy);
            auto it = m_cells.find(cellKey);
            if (it == m_cells.end())
                continue;

            for (uint64_t guid : it->second.friendlyGuids)
            {
                result.push_back(guid);
            }
        }
    }

    return result;
}

void MapSpatialIndex::Clear()
{
    m_cells.clear();
    m_unitCells.clear();
}

// =============================================================================
// WorldSpatialIndex Implementation
// =============================================================================

MapSpatialIndex& WorldSpatialIndex::GetMapIndex(uint32_t mapId)
{
    auto it = m_mapIndices.find(mapId);
    if (it != m_mapIndices.end())
        return it->second;

    return m_mapIndices.emplace(mapId, MapSpatialIndex(mapId)).first->second;
}

void WorldSpatialIndex::UpdateUnit(uint32_t mapId, uint64_t guid, float x, float y, bool isHostile, bool isFriendly)
{
    GetMapIndex(mapId).UpdateUnit(guid, x, y, isHostile, isFriendly);
}

void WorldSpatialIndex::RemoveUnit(uint32_t mapId, uint64_t guid)
{
    auto it = m_mapIndices.find(mapId);
    if (it != m_mapIndices.end())
        it->second.RemoveUnit(guid);
}

void WorldSpatialIndex::Clear()
{
    m_mapIndices.clear();
}

// =============================================================================
// TargetCacheManager Implementation
// =============================================================================

BotTargetCache& TargetCacheManager::GetCache(EntityId entity)
{
    uint32_t key = static_cast<uint32_t>(entity.value);
    auto it = m_caches.find(key);
    if (it != m_caches.end())
        return it->second;

    BotTargetCache& cache = m_caches[key];
    cache.entity = entity;
    return cache;
}

BotTargetCache& TargetCacheManager::GetCacheByGuid(uint64_t playerGuid)
{
    auto it = m_guidToEntity.find(playerGuid);
    if (it != m_guidToEntity.end())
        return GetCache(it->second);

    // Create new cache with invalid entity - will be updated on registration
    EntityId entity = EntityId::Invalid();
    BotTargetCache& cache = GetCache(entity);
    cache.playerGuid = playerGuid;
    return cache;
}

void TargetCacheManager::RemoveCache(EntityId entity)
{
    uint32_t key = static_cast<uint32_t>(entity.value);
    auto it = m_caches.find(key);
    if (it != m_caches.end())
    {
        m_guidToEntity.erase(it->second.playerGuid);
        m_caches.erase(it);
    }
}

void TargetCacheManager::RemoveCacheByGuid(uint64_t playerGuid)
{
    auto it = m_guidToEntity.find(playerGuid);
    if (it != m_guidToEntity.end())
    {
        RemoveCache(it->second);
    }
}

void TargetCacheManager::InvalidateNearby(uint32_t mapId, float x, float y, float radius)
{
    // Invalidate caches for all bots on this map near the event
    // This is called when combat state changes (unit death, aggro, etc.)
    for (auto& [key, cache] : m_caches)
    {
        // For simplicity, invalidate all on the same map
        // TODO: Use spatial index to only invalidate nearby bots
        cache.InvalidateAll();
    }
}

void TargetCacheManager::InvalidateAll()
{
    for (auto& [key, cache] : m_caches)
    {
        cache.InvalidateAll();
    }
}

std::vector<uint64_t> TargetCacheManager::GetAttackers(PlayerbotAI* botAI, Player* player, uint32_t now)
{
    if (!botAI || !player)
        return {};

    uint64_t guid = player->GetGUID().GetRawValue();
    BotTargetCache& cache = GetCacheByGuid(guid);

    // Check cache validity
    if (cache.attackers.IsValid(now))
    {
        ++m_cacheHits;
        return cache.attackers.guids;
    }

    // Cache miss - recalculate
    ++m_cacheMisses;

    std::vector<uint64_t> attackers = CalculateAttackers(botAI, player);
    cache.attackers.Update(attackers, now, BotTargetCache::ATTACKER_TTL);
    cache.lastAttackerUpdate = now;

    return attackers;
}

std::vector<uint64_t> TargetCacheManager::GetPossibleTargets(PlayerbotAI* botAI, Player* player, uint32_t now, float range)
{
    if (!botAI || !player)
        return {};

    uint64_t guid = player->GetGUID().GetRawValue();
    BotTargetCache& cache = GetCacheByGuid(guid);

    // Check cache validity
    if (cache.possibleTargets.IsValid(now))
    {
        ++m_cacheHits;
        return cache.possibleTargets.guids;
    }

    // Cache miss - recalculate
    ++m_cacheMisses;

    if (range <= 0.0f)
        range = sPlayerbotAIConfig->sightDistance;

    std::vector<uint64_t> targets = CalculatePossibleTargets(player, range);
    cache.possibleTargets.Update(targets, now, BotTargetCache::POSSIBLE_TARGET_TTL);
    cache.lastPossibleTargetUpdate = now;

    return targets;
}

std::vector<uint64_t> TargetCacheManager::GetFriendlyTargets(PlayerbotAI* botAI, Player* player, uint32_t now, float range)
{
    if (!botAI || !player)
        return {};

    uint64_t guid = player->GetGUID().GetRawValue();
    BotTargetCache& cache = GetCacheByGuid(guid);

    // Check cache validity
    if (cache.friendlyTargets.IsValid(now))
    {
        ++m_cacheHits;
        return cache.friendlyTargets.guids;
    }

    // Cache miss - recalculate
    ++m_cacheMisses;

    if (range <= 0.0f)
        range = sPlayerbotAIConfig->sightDistance;

    std::vector<uint64_t> targets = CalculateFriendlyTargets(player, range);
    cache.friendlyTargets.Update(targets, now, BotTargetCache::FRIENDLY_TTL);
    cache.lastFriendlyUpdate = now;

    return targets;
}

std::vector<uint64_t> TargetCacheManager::CalculateAttackers(PlayerbotAI* botAI, Player* player)
{
    std::unordered_set<uint64_t> attackerSet;

    // Get units with threat on this player
    HostileRefMgr& refManager = player->getHostileRefMgr();
    HostileReference* ref = refManager.getFirst();

    while (ref)
    {
        ThreatMgr* threatMgr = ref->GetSource();
        Unit* attacker = threatMgr->GetOwner();

        if (attacker && attacker->IsAlive() && !attacker->IsFriendlyTo(player))
        {
            attackerSet.insert(attacker->GetGUID().GetRawValue());
        }

        ref = ref->next();
    }

    // Also check group members' attackers
    if (Group* group = player->GetGroup())
    {
        Group::MemberSlotList const& members = group->GetMemberSlots();
        for (auto& memberSlot : members)
        {
            Player* member = ObjectAccessor::FindPlayer(memberSlot.guid);
            if (!member || member == player || !member->IsAlive())
                continue;

            if (member->GetMapId() != player->GetMapId())
                continue;

            float dist = player->GetDistance2d(member);
            if (dist > sPlayerbotAIConfig->sightDistance)
                continue;

            HostileRefMgr& memberRef = member->getHostileRefMgr();
            HostileReference* mRef = memberRef.getFirst();

            while (mRef)
            {
                ThreatMgr* threatMgr = mRef->GetSource();
                Unit* attacker = threatMgr->GetOwner();

                if (attacker && attacker->IsAlive() && !attacker->IsFriendlyTo(player))
                {
                    attackerSet.insert(attacker->GetGUID().GetRawValue());
                }

                mRef = mRef->next();
            }
        }
    }

    return std::vector<uint64_t>(attackerSet.begin(), attackerSet.end());
}

std::vector<uint64_t> TargetCacheManager::CalculatePossibleTargets(Player* player, float range)
{
    std::vector<uint64_t> targets;

    // Use spatial index for fast lookup
    uint32_t mapId = player->GetMapId();
    float x = player->GetPositionX();
    float y = player->GetPositionY();

    MapSpatialIndex& index = sWorldSpatialIndex.GetMapIndex(mapId);
    std::vector<uint64_t> nearby = index.FindHostilesInRange(x, y, range);

    // Filter results
    for (uint64_t guid : nearby)
    {
        Unit* unit = ObjectAccessor::GetUnit(*player, ObjectGuid(guid));
        if (!unit)
            continue;

        if (!unit->IsAlive())
            continue;

        if (unit->IsFriendlyTo(player))
            continue;

        // Distance check (spatial index gives approximate results)
        if (player->GetDistance(unit) > range)
            continue;

        targets.push_back(guid);
    }

    return targets;
}

std::vector<uint64_t> TargetCacheManager::CalculateFriendlyTargets(Player* player, float range)
{
    std::vector<uint64_t> targets;

    // Add group/raid members
    if (Group* group = player->GetGroup())
    {
        Group::MemberSlotList const& members = group->GetMemberSlots();
        for (auto& memberSlot : members)
        {
            Player* member = ObjectAccessor::FindPlayer(memberSlot.guid);
            if (!member || !member->IsAlive())
                continue;

            if (member->GetMapId() != player->GetMapId())
                continue;

            if (player->GetDistance(member) > range)
                continue;

            targets.push_back(member->GetGUID().GetRawValue());
        }
    }

    return targets;
}

// =============================================================================
// ValueCacheSystem Implementation
// =============================================================================

void ValueCacheSystem::Update(Registry& registry, uint32_t now)
{
    uint32_t startTime = getMSTime();
    uint32_t botsUpdated = 0;

    registry.ForEach<BotLink, ValueCache>([&](EntityId id, BotLink& link, ValueCache& cache) {
        if (!link.player || !link.botAI)
            return;

        // Check if update is needed
        if (now - cache.lastUpdate < ValueCache::UPDATE_INTERVAL)
            return;

        UpdateBot(id, registry, now);
        ++botsUpdated;
    });

    float elapsed = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));

    s_metrics.botsUpdated = botsUpdated;
    s_metrics.updateTimeMs = elapsed;
    s_metrics.avgUpdateTimeMs = s_metrics.avgUpdateTimeMs * 0.9f + elapsed * 0.1f;
}

void ValueCacheSystem::UpdateBot(EntityId entity, Registry& registry, uint32_t now)
{
    BotLink* link = registry.GetComponent<BotLink>(entity);
    ValueCache* cache = registry.GetComponent<ValueCache>(entity);

    if (!link || !cache || !link->player)
        return;

    Player* player = link->player;

    // Update health/power from ECS components (very fast)
    if (Health* health = registry.GetComponent<Health>(entity))
    {
        cache->healthPercent = health->Percent();
        cache->isLowHealth = health->IsLow();
    }

    if (Power* power = registry.GetComponent<Power>(entity))
    {
        cache->powerPercent = power->Percent();
        cache->isLowPower = power->IsLow();
    }

    // Update combat info (less frequent)
    if (now - cache->lastCombatInfoUpdate >= ValueCache::COMBAT_UPDATE_INTERVAL)
    {
        // Get cached attackers
        auto attackers = sTargetCacheManager.GetAttackers(link->botAI, player, now);
        cache->attackerCount = static_cast<uint32_t>(attackers.size());
        cache->hasAttackers = !attackers.empty();

        // Get cached possible targets
        auto targets = sTargetCacheManager.GetPossibleTargets(link->botAI, player, now, 0.0f);
        cache->possibleTargetCount = static_cast<uint32_t>(targets.size());
        cache->hasPossibleTargets = !targets.empty();

        cache->lastCombatInfoUpdate = now;
    }

    // Update party info (even less frequent)
    if (now - cache->lastPartyInfoUpdate >= ValueCache::PARTY_UPDATE_INTERVAL)
    {
        if (Group* group = player->GetGroup())
        {
            cache->partySize = group->GetMembersCount();

            // Check for low health party members
            bool anyLow = false;
            uint32_t healCount = 0;

            Group::MemberSlotList const& members = group->GetMemberSlots();
            for (auto& memberSlot : members)
            {
                Player* member = ObjectAccessor::FindPlayer(memberSlot.guid);
                if (!member || !member->IsAlive())
                    continue;

                float healthPct = member->GetHealthPct();
                if (healthPct < 90.0f)
                {
                    ++healCount;
                    if (healthPct < 30.0f)
                        anyLow = true;
                }
            }

            cache->healTargetCount = healCount;
            cache->anyPartyMemberLowHealth = anyLow;
        }
        else
        {
            cache->partySize = 1;
            cache->healTargetCount = 0;
            cache->anyPartyMemberLowHealth = false;
        }

        cache->lastPartyInfoUpdate = now;
    }

    cache->lastUpdate = now;
}

// =============================================================================
// CachedValues Namespace Implementation
// =============================================================================

namespace CachedValues {

std::vector<uint64_t> GetAttackers(PlayerbotAI* botAI)
{
    if (!botAI || !botAI->GetBot())
        return {};

    return sTargetCacheManager.GetAttackers(botAI, botAI->GetBot(), getMSTime());
}

std::vector<uint64_t> GetPossibleTargets(PlayerbotAI* botAI, float range)
{
    if (!botAI || !botAI->GetBot())
        return {};

    return sTargetCacheManager.GetPossibleTargets(botAI, botAI->GetBot(), getMSTime(), range);
}

std::vector<uint64_t> GetFriendlyTargets(PlayerbotAI* botAI, float range)
{
    if (!botAI || !botAI->GetBot())
        return {};

    return sTargetCacheManager.GetFriendlyTargets(botAI, botAI->GetBot(), getMSTime(), range);
}

float GetHealthPercent(PlayerbotAI* botAI)
{
    if (!botAI)
        return 100.0f;

    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (!entity.IsValid())
        return botAI->GetBot()->GetHealthPct();

    Health* health = sBotRegistry.GetRegistry().GetComponent<Health>(entity);
    return health ? health->Percent() : botAI->GetBot()->GetHealthPct();
}

float GetPowerPercent(PlayerbotAI* botAI)
{
    if (!botAI)
        return 100.0f;

    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (!entity.IsValid())
    {
        Player* player = botAI->GetBot();
        Powers pt = player->getPowerType();
        uint32_t max = player->GetMaxPower(pt);
        return max > 0 ? (100.0f * player->GetPower(pt) / max) : 0.0f;
    }

    Power* power = sBotRegistry.GetRegistry().GetComponent<Power>(entity);
    return power ? power->Percent() : 0.0f;
}

bool IsLowHealth(PlayerbotAI* botAI, float threshold)
{
    return GetHealthPercent(botAI) < threshold;
}

bool IsLowPower(PlayerbotAI* botAI, float threshold)
{
    return GetPowerPercent(botAI) < threshold;
}

bool IsInCombat(PlayerbotAI* botAI)
{
    if (!botAI)
        return false;

    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (!entity.IsValid())
        return botAI->GetBot()->IsInCombat();

    CombatState* combat = sBotRegistry.GetRegistry().GetComponent<CombatState>(entity);
    return combat ? combat->inCombat : botAI->GetBot()->IsInCombat();
}

bool HasAttackers(PlayerbotAI* botAI)
{
    if (!botAI)
        return false;

    auto attackers = GetAttackers(botAI);
    return !attackers.empty();
}

uint32_t GetAttackerCount(PlayerbotAI* botAI)
{
    if (!botAI)
        return 0;

    auto attackers = GetAttackers(botAI);
    return static_cast<uint32_t>(attackers.size());
}

float GetDistanceToTarget(PlayerbotAI* botAI, Unit* target)
{
    if (!botAI || !target)
        return 0.0f;

    // Use ECS position if available
    EntityId entity = sBotRegistry.GetEntityByGuid(botAI->GetBot()->GetGUID().GetRawValue());
    if (entity.IsValid())
    {
        Position* pos = sBotRegistry.GetRegistry().GetComponent<Position>(entity);
        if (pos)
        {
            float dx = pos->x - target->GetPositionX();
            float dy = pos->y - target->GetPositionY();
            float dz = pos->z - target->GetPositionZ();
            return std::sqrt(dx*dx + dy*dy + dz*dz);
        }
    }

    return botAI->GetBot()->GetDistance(target);
}

float GetDistanceToTarget(PlayerbotAI* botAI, uint64_t targetGuid)
{
    if (!botAI)
        return 0.0f;

    Unit* target = ObjectAccessor::GetUnit(*botAI->GetBot(), ObjectGuid(targetGuid));
    return target ? GetDistanceToTarget(botAI, target) : 0.0f;
}

void RegisterBot(PlayerbotAI* botAI, Player* player)
{
    if (!botAI || !player)
        return;

    uint64_t guid = player->GetGUID().GetRawValue();
    EntityId entity = sBotRegistry.GetEntityByGuid(guid);

    if (entity.IsValid())
    {
        // Ensure bot has ValueCache component
        if (!sBotRegistry.GetRegistry().HasComponent<ValueCache>(entity))
        {
            sBotRegistry.GetRegistry().AddComponent<ValueCache>(entity);
        }

        // Register with target cache manager
        BotTargetCache& cache = sTargetCacheManager.GetCache(entity);
        cache.entity = entity;
        cache.playerGuid = guid;
    }
}

void UnregisterBot(uint64_t playerGuid)
{
    sTargetCacheManager.RemoveCacheByGuid(playerGuid);
}

} // namespace CachedValues

} // namespace ecs
