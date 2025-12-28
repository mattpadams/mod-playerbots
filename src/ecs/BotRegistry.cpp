/*
 * BotRegistry Implementation
 *
 * Bridges ECS with existing PlayerbotAI system.
 */

#include "BotRegistry.h"
#include "ValueCache.h"
#include "Player.h"
#include "PlayerbotAI.h"
#include "Spell.h"
#include "Timer.h"
#include "Log.h"

namespace ecs {

void BotRegistry::Initialize(size_t expectedBotCount)
{
    if (m_initialized)
        return;

    LOG_INFO("playerbots", "ECS BotRegistry: Initializing with capacity for {} bots", expectedBotCount);

    // Pre-register all component types
    m_registry.RegisterComponent<Position>();
    m_registry.RegisterComponent<Velocity>();
    m_registry.RegisterComponent<PathState>();
    m_registry.RegisterComponent<Health>();
    m_registry.RegisterComponent<Power>();
    m_registry.RegisterComponent<Stats>();
    m_registry.RegisterComponent<Target>();
    m_registry.RegisterComponent<ThreatList>();
    m_registry.RegisterComponent<CombatState>();
    m_registry.RegisterComponent<Cooldowns>();
    m_registry.RegisterComponent<AIState>();
    m_registry.RegisterComponent<BotRole>();
    m_registry.RegisterComponent<SquadMember>();
    m_registry.RegisterComponent<BotLink>();
    m_registry.RegisterComponent<Dirty>();
    m_registry.RegisterComponent<Timers>();
    m_registry.RegisterComponent<ValueCache>();

    // Pre-allocate storage
    m_registry.Reserve(expectedBotCount);
    m_guidToEntity.reserve(expectedBotCount);

    m_initialized = true;
    LOG_INFO("playerbots", "ECS BotRegistry: Initialization complete");
}

void BotRegistry::Shutdown()
{
    if (!m_initialized)
        return;

    LOG_INFO("playerbots", "ECS BotRegistry: Shutting down ({} bots registered)", m_guidToEntity.size());

    m_guidToEntity.clear();
    m_registry.Clear();
    m_initialized = false;
}

EntityId BotRegistry::RegisterBot(PlayerbotAI* botAI, Player* player)
{
    if (!m_initialized || !botAI || !player)
        return EntityId::Invalid();

    uint64_t guid = player->GetGUID().GetRawValue();

    // Check if already registered
    auto it = m_guidToEntity.find(guid);
    if (it != m_guidToEntity.end())
    {
        // Already registered, update the link
        if (BotLink* link = m_registry.GetComponent<BotLink>(it->second))
        {
            link->botAI = botAI;
            link->player = player;
        }
        return it->second;
    }

    // Create new entity
    EntityId entity = m_registry.CreateEntity(EntityType::Bot);

    // Add core components
    BotLink& link = m_registry.AddComponent<BotLink>(entity);
    link.botAI = botAI;
    link.player = player;
    link.playerGuid = guid;

    // Add spatial components
    m_registry.AddComponent<Position>(entity);
    m_registry.AddComponent<Velocity>(entity);

    // Add vital components
    m_registry.AddComponent<Health>(entity);
    m_registry.AddComponent<Power>(entity);
    m_registry.AddComponent<Stats>(entity);

    // Add combat components
    m_registry.AddComponent<Target>(entity);
    m_registry.AddComponent<CombatState>(entity);

    // Add AI components
    m_registry.AddComponent<AIState>(entity);
    m_registry.AddComponent<BotRole>(entity);

    // Add utility components
    m_registry.AddComponent<Dirty>(entity);
    Timers& timers = m_registry.AddComponent<Timers>(entity);
    timers.created = getMSTime();

    // Add value cache component
    m_registry.AddComponent<ValueCache>(entity);

    // Register in lookup map
    m_guidToEntity[guid] = entity;

    // Register with target cache manager
    CachedValues::RegisterBot(botAI, player);

    // Initial sync from WoW state
    SyncEntityFromWoW(entity);

    return entity;
}

void BotRegistry::UnregisterBot(EntityId entity)
{
    if (!m_initialized || !m_registry.IsAlive(entity))
        return;

    // Find and remove from GUID map
    if (const BotLink* link = m_registry.GetComponent<BotLink>(entity))
    {
        CachedValues::UnregisterBot(link->playerGuid);
        m_guidToEntity.erase(link->playerGuid);
    }

    m_registry.DestroyEntity(entity);
}

void BotRegistry::UnregisterBot(uint64_t playerGuid)
{
    auto it = m_guidToEntity.find(playerGuid);
    if (it != m_guidToEntity.end())
    {
        CachedValues::UnregisterBot(playerGuid);
        m_registry.DestroyEntity(it->second);
        m_guidToEntity.erase(it);
    }
}

EntityId BotRegistry::GetEntityByGuid(uint64_t playerGuid) const
{
    auto it = m_guidToEntity.find(playerGuid);
    return it != m_guidToEntity.end() ? it->second : EntityId::Invalid();
}

bool BotRegistry::IsRegistered(uint64_t playerGuid) const
{
    return m_guidToEntity.find(playerGuid) != m_guidToEntity.end();
}

bool BotRegistry::IsRegistered(EntityId entity) const
{
    return m_registry.IsAlive(entity) && m_registry.HasComponent<BotLink>(entity);
}

void BotRegistry::SyncFromWoW()
{
    uint32_t startTime = getMSTime();

    m_registry.ForEach<BotLink>([this](EntityId id, BotLink& link) {
        if (link.player && link.botAI)
        {
            SyncEntityFromWoW(id);
        }
    });

    uint32_t elapsed = getMSTimeDiff(startTime, getMSTime());

    // Update rolling average
    m_metrics.avgSyncTimeMs = m_metrics.avgSyncTimeMs * 0.9f + elapsed * 0.1f;
}

void BotRegistry::SyncEntityFromWoW(EntityId entity)
{
    BotLink* link = m_registry.GetComponent<BotLink>(entity);
    if (!link || !link->player)
        return;

    Player* player = link->player;
    uint32_t now = getMSTime();

    // Sync position (high frequency)
    if (Position* pos = m_registry.GetComponent<Position>(entity))
    {
        SyncSystem::SyncPosition(player, *pos);
    }

    // Sync vitals (high frequency during combat)
    if (Health* health = m_registry.GetComponent<Health>(entity))
    {
        Power* power = m_registry.GetComponent<Power>(entity);
        if (power)
        {
            SyncSystem::SyncVitals(player, *health, *power);
        }
    }

    // Sync combat state
    if (CombatState* combat = m_registry.GetComponent<CombatState>(entity))
    {
        SyncSystem::SyncCombatState(player, *combat);
    }

    // Sync stats (low frequency - only when dirty)
    if (link->needsPositionSync)  // Reusing flag for full sync
    {
        if (Stats* stats = m_registry.GetComponent<Stats>(entity))
        {
            SyncSystem::SyncStats(player, *stats);
        }
        link->needsPositionSync = false;
    }

    link->lastSyncTime = now;
}

void BotRegistry::UpdateMetrics()
{
    m_metrics.totalBots = static_cast<uint32_t>(m_guidToEntity.size());
    m_metrics.botsInCombat = 0;
    m_metrics.botsMoving = 0;
    std::memset(m_metrics.botsByMap, 0, sizeof(m_metrics.botsByMap));

    m_registry.ForEach<BotLink>([this](EntityId id, BotLink& link) {
        if (const Position* pos = m_registry.GetComponent<Position>(id))
        {
            if (pos->mapId < 1000)
            {
                m_metrics.botsByMap[pos->mapId]++;
            }
        }

        if (const CombatState* combat = m_registry.GetComponent<CombatState>(id))
        {
            if (combat->inCombat)
                m_metrics.botsInCombat++;
        }

        if (const Velocity* vel = m_registry.GetComponent<Velocity>(id))
        {
            if (vel->isMoving)
                m_metrics.botsMoving++;
        }
    });

    m_metrics.lastUpdateTime = getMSTime();
}

// =============================================================================
// SyncSystem Implementation
// =============================================================================

void SyncSystem::SyncPosition(Player* player, Position& pos)
{
    pos.x = player->GetPositionX();
    pos.y = player->GetPositionY();
    pos.z = player->GetPositionZ();
    pos.orientation = player->GetOrientation();
    pos.mapId = player->GetMapId();
    pos.zoneId = player->GetZoneId();
    pos.areaId = player->GetAreaId();

    // Compute spatial cell (32-yard cells)
    constexpr float CELL_SIZE = 32.0f;
    pos.cellX = static_cast<int32_t>(pos.x / CELL_SIZE);
    pos.cellY = static_cast<int32_t>(pos.y / CELL_SIZE);
}

void SyncSystem::SyncVitals(Player* player, Health& health, Power& power)
{
    // Health
    health.current = player->GetHealth();
    health.max = player->GetMaxHealth();
    health.isDead = player->isDead();
    health.isGhost = player->HasFlag(PLAYER_FLAGS, PLAYER_FLAGS_GHOST);

    // Power - detect type from class
    Powers powerType = player->getPowerType();
    switch (powerType)
    {
        case POWER_MANA:
            power.powerType = Power::Type::Mana;
            break;
        case POWER_RAGE:
            power.powerType = Power::Type::Rage;
            break;
        case POWER_ENERGY:
            power.powerType = Power::Type::Energy;
            break;
        case POWER_RUNIC_POWER:
            power.powerType = Power::Type::Runic;
            break;
        default:
            power.powerType = Power::Type::Mana;
            break;
    }

    power.current = player->GetPower(powerType);
    power.max = player->GetMaxPower(powerType);
}

void SyncSystem::SyncCombatState(Player* player, CombatState& combat)
{
    combat.inCombat = player->IsInCombat();
    combat.isAttacking = player->GetVictim() != nullptr;  // Has a target being attacked
    combat.isCasting = player->IsNonMeleeSpellCast(false);
    combat.isChanneling = player->GetCurrentSpell(CURRENT_CHANNELED_SPELL) != nullptr;
    combat.isStunned = player->HasUnitState(UNIT_STATE_STUNNED);
    combat.isFeared = player->HasUnitState(UNIT_STATE_FLEEING);
    combat.isRooted = player->HasUnitState(UNIT_STATE_ROOT);

    if (combat.isCasting)
    {
        if (Spell* spell = player->GetCurrentSpell(CURRENT_GENERIC_SPELL))
        {
            combat.castingSpellId = spell->m_spellInfo->Id;
        }
    }
    else
    {
        combat.castingSpellId = 0;
    }
}

void SyncSystem::SyncStats(Player* player, Stats& stats)
{
    stats.level = player->GetLevel();
    stats.classId = player->getClass();
    stats.raceId = player->getRace();
    stats.attackPower = player->GetTotalAttackPowerValue(BASE_ATTACK);
    stats.spellPower = player->GetBaseSpellPowerBonus();
    stats.critChance = player->GetFloatValue(PLAYER_CRIT_PERCENTAGE);
    stats.armor = player->GetArmor();
}

void SyncSystem::SyncAll(EntityId entity, Registry& registry)
{
    BotLink* link = registry.GetComponent<BotLink>(entity);
    if (!link || !link->player)
        return;

    Player* player = link->player;

    if (Position* pos = registry.GetComponent<Position>(entity))
        SyncPosition(player, *pos);

    if (Health* health = registry.GetComponent<Health>(entity))
    {
        if (Power* power = registry.GetComponent<Power>(entity))
            SyncVitals(player, *health, *power);
    }

    if (CombatState* combat = registry.GetComponent<CombatState>(entity))
        SyncCombatState(player, *combat);

    if (Stats* stats = registry.GetComponent<Stats>(entity))
        SyncStats(player, *stats);
}

} // namespace ecs
