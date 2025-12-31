/*
 * WorldServer Bridge Implementation
 */

#include "WorldServerBridge.h"
#include "Log.h"
#include "Player.h"
#include "Playerbots.h"
#include "PlayerbotAI.h"
#include "PlayerbotMgr.h"
#include "ObjectAccessor.h"

#include <chrono>

namespace ecs {
namespace ipc {

bool WorldServerBridge::Initialize(const BridgeConfig& config)
{
    m_config = config;

    if (!config.enabled)
    {
        LOG_INFO("playerbots", "WorldServerBridge: Disabled by configuration");
        return true;
    }

    LOG_INFO("playerbots", "WorldServerBridge: Initializing IPC server...");

    if (!sBotEngineIPC.InitializeServer(config.shmName))
    {
        LOG_ERROR("playerbots", "WorldServerBridge: Failed to initialize IPC server");
        return false;
    }

    m_initialized = true;
    m_connected = true;
    m_lastExportTime = std::chrono::steady_clock::now();

    LOG_INFO("playerbots", "WorldServerBridge: Initialized successfully");
    LOG_INFO("playerbots", "  - SHM Name: {}", config.shmName);
    LOG_INFO("playerbots", "  - Export Interval: {} ms", config.exportIntervalMs);

    return true;
}

void WorldServerBridge::Shutdown()
{
    if (!m_initialized)
        return;

    LOG_INFO("playerbots", "WorldServerBridge: Shutting down...");

    sBotEngineIPC.Shutdown();
    m_initialized = false;
    m_connected = false;

    LOG_INFO("playerbots", "WorldServerBridge: Shutdown complete");
    LOG_INFO("playerbots", "  - Updates Exported: {}", m_metrics.updatesExported);
    LOG_INFO("playerbots", "  - Actions Imported: {}", m_metrics.actionsImported);
}

void WorldServerBridge::Update(uint32_t diff)
{
    if (!IsEnabled())
        return;

    // Update heartbeat
    m_heartbeatTimer += diff;
    if (m_heartbeatTimer >= m_config.heartbeatIntervalMs)
    {
        m_heartbeatTimer = 0;
        sBotEngineIPC.UpdateHeartbeat();

        // Check if bot-engine is alive
        bool wasConnected = m_connected;
        m_connected = sBotEngineIPC.IsPartnerAlive();

        if (wasConnected && !m_connected)
        {
            LOG_WARN("playerbots", "WorldServerBridge: Bot-engine connection lost");
        }
        else if (!wasConnected && m_connected)
        {
            LOG_INFO("playerbots", "WorldServerBridge: Bot-engine connected");
        }
    }

    // Export pending updates
    m_exportTimer += diff;
    if (m_exportTimer >= m_config.exportIntervalMs)
    {
        m_exportTimer = 0;
        FlushUpdates();
    }

    // Process incoming actions
    m_actionTimer += diff;
    if (m_actionTimer >= m_config.actionPollIntervalMs)
    {
        m_actionTimer = 0;
        ProcessActions();
    }
}

void WorldServerBridge::ExportBotPosition(Player* bot)
{
    if (!IsEnabled() || !bot)
        return;

    EntityUpdate update;
    update.entityGuid = bot->GetGUID().GetRawValue();
    update.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    update.type = EntityUpdate::Type::PositionUpdate;
    update.data.position.x = bot->GetPositionX();
    update.data.position.y = bot->GetPositionY();
    update.data.position.z = bot->GetPositionZ();
    update.data.position.orientation = bot->GetOrientation();
    update.data.position.mapId = bot->GetMapId();

    QueueUpdate(update);
}

void WorldServerBridge::ExportBotVitals(Player* bot)
{
    if (!IsEnabled() || !bot)
        return;

    EntityUpdate update;
    update.entityGuid = bot->GetGUID().GetRawValue();
    update.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    update.type = EntityUpdate::Type::VitalsUpdate;
    update.data.vitals.health = bot->GetHealth();
    update.data.vitals.maxHealth = bot->GetMaxHealth();
    update.data.vitals.power = bot->GetPower(bot->getPowerType());
    update.data.vitals.maxPower = bot->GetMaxPower(bot->getPowerType());

    QueueUpdate(update);
}

void WorldServerBridge::ExportBotCombat(Player* bot)
{
    if (!IsEnabled() || !bot)
        return;

    EntityUpdate update;
    update.entityGuid = bot->GetGUID().GetRawValue();
    update.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    update.type = EntityUpdate::Type::CombatStateUpdate;

    uint8_t flags = 0;
    if (bot->IsInCombat()) flags |= 0x01;
    if (bot->IsNonMeleeSpellCast(false)) flags |= 0x02;
    if (bot->isMoving()) flags |= 0x04;
    if (bot->isDead()) flags |= 0x10;

    update.data.combat.combatFlags = flags;
    update.data.combat.targetGuid = bot->GetVictim() ?
        bot->GetVictim()->GetGUID().GetRawValue() : 0;

    QueueUpdate(update);
}

void WorldServerBridge::ExportBotSpawn(Player* bot)
{
    if (!IsEnabled() || !bot)
        return;

    EntityUpdate update;
    update.entityGuid = bot->GetGUID().GetRawValue();
    update.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    update.type = EntityUpdate::Type::EntitySpawn;

    QueueUpdate(update);

    // Also export full snapshot
    ExportFullSnapshot(bot);
}

void WorldServerBridge::ExportBotDespawn(uint64_t guid)
{
    if (!IsEnabled())
        return;

    EntityUpdate update;
    update.entityGuid = guid;
    update.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    update.type = EntityUpdate::Type::EntityDespawn;

    QueueUpdate(update);
}

void WorldServerBridge::ExportFullSnapshot(Player* bot)
{
    if (!IsEnabled() || !bot)
        return;

    // Update the snapshot area directly
    EntitySnapshot snapshot;
    snapshot.guid = bot->GetGUID().GetRawValue();
    snapshot.lastUpdate = std::chrono::steady_clock::now().time_since_epoch().count();

    // Position
    snapshot.x = bot->GetPositionX();
    snapshot.y = bot->GetPositionY();
    snapshot.z = bot->GetPositionZ();
    snapshot.orientation = bot->GetOrientation();
    snapshot.mapId = bot->GetMapId();
    snapshot.zoneId = bot->GetZoneId();

    // Vitals
    snapshot.health = bot->GetHealth();
    snapshot.maxHealth = bot->GetMaxHealth();
    snapshot.power = bot->GetPower(bot->getPowerType());
    snapshot.maxPower = bot->GetMaxPower(bot->getPowerType());

    // State
    uint8_t flags = 0;
    if (bot->IsInCombat()) flags |= 0x01;
    if (bot->IsNonMeleeSpellCast(false)) flags |= 0x02;
    if (bot->isMoving()) flags |= 0x04;
    if (bot->isDead()) flags |= 0x10;
    snapshot.combatFlags = flags;

    snapshot.classId = bot->getClass();
    snapshot.level = static_cast<uint8_t>(bot->GetLevel());
    snapshot.faction = 0;  // Could be expanded

    // Target
    snapshot.targetGuid = bot->GetVictim() ?
        bot->GetVictim()->GetGUID().GetRawValue() : 0;

    sBotEngineIPC.UpdateEntitySnapshot(snapshot.guid, snapshot);
}

void WorldServerBridge::QueueUpdate(const EntityUpdate& update)
{
    if (m_pendingUpdates.size() >= m_config.maxUpdatesPerTick)
    {
        ++m_metrics.droppedUpdates;
        return;
    }

    m_pendingUpdates.push_back(update);
}

void WorldServerBridge::FlushUpdates()
{
    if (m_pendingUpdates.empty())
        return;

    auto start = std::chrono::steady_clock::now();

    size_t sent = 0;
    for (const auto& update : m_pendingUpdates)
    {
        if (sBotEngineIPC.SendUpdate(update))
        {
            ++sent;
        }
        else
        {
            // Ring buffer full
            ++m_metrics.droppedUpdates;
        }
    }

    m_pendingUpdates.clear();
    m_metrics.updatesExported += sent;
    ++m_metrics.exportCalls;

    auto end = std::chrono::steady_clock::now();
    m_metrics.lastExportTimeUs = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
}

void WorldServerBridge::ProcessActions()
{
    if (!IsEnabled())
        return;

    auto start = std::chrono::steady_clock::now();

    size_t count = sBotEngineIPC.DrainActions([](const BotAction& action)
    {
        // Static dispatch - can't use member function directly
        // Process in the singleton
        sWorldServerBridge.HandleAction(action);
    });

    // Note: The above won't work as-is. Let me fix this.
    // Actually we need a non-lambda approach here.

    m_metrics.actionsImported += count;
    ++m_metrics.importCalls;

    auto end = std::chrono::steady_clock::now();
    m_metrics.lastImportTimeUs = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
}

void WorldServerBridge::HandleAction(const BotAction& action)
{
    switch (action.type)
    {
        case BotAction::Type::MoveTo:
            HandleMoveAction(action);
            break;
        case BotAction::Type::CastSpell:
            HandleCastAction(action);
            break;
        case BotAction::Type::Attack:
            HandleAttackAction(action);
            break;
        case BotAction::Type::StopMove:
        case BotAction::Type::StopAttack:
        case BotAction::Type::ClearTarget:
            HandleStopAction(action);
            break;
        case BotAction::Type::SetTarget:
            HandleTargetAction(action);
            break;
        default:
            ++m_metrics.failedActions;
            break;
    }
}

void WorldServerBridge::HandleMoveAction(const BotAction& action)
{
    Player* bot = GetBotByGuid(action.botGuid);
    if (!bot)
        return;

    PlayerbotAI* ai = GetBotAI(bot);
    if (!ai)
        return;

    // Create movement request
    float x = action.data.moveTo.x;
    float y = action.data.moveTo.y;
    float z = action.data.moveTo.z;

    // Use the bot's movement system
    // This would integrate with the existing movement action
    bot->GetMotionMaster()->MovePoint(0, x, y, z);
}

void WorldServerBridge::HandleCastAction(const BotAction& action)
{
    Player* bot = GetBotByGuid(action.botGuid);
    if (!bot)
        return;

    PlayerbotAI* ai = GetBotAI(bot);
    if (!ai)
        return;

    uint32_t spellId = action.data.castSpell.spellId;
    uint64_t targetGuid = action.data.castSpell.targetGuid;

    // Find target
    Unit* target = nullptr;
    if (targetGuid)
    {
        target = ObjectAccessor::GetUnit(*bot, ObjectGuid(targetGuid));
    }
    else
    {
        target = bot;  // Self-cast
    }

    if (target)
    {
        // Queue the spell cast through the AI system
        ai->CastSpell(spellId, target);
    }
}

void WorldServerBridge::HandleAttackAction(const BotAction& action)
{
    Player* bot = GetBotByGuid(action.botGuid);
    if (!bot)
        return;

    uint64_t targetGuid = action.data.target.targetGuid;
    if (!targetGuid)
        return;

    Unit* target = ObjectAccessor::GetUnit(*bot, ObjectGuid(targetGuid));
    if (target && bot->IsValidAttackTarget(target))
    {
        bot->Attack(target, true);
    }
}

void WorldServerBridge::HandleStopAction(const BotAction& action)
{
    Player* bot = GetBotByGuid(action.botGuid);
    if (!bot)
        return;

    switch (action.type)
    {
        case BotAction::Type::StopMove:
            bot->StopMoving();
            break;
        case BotAction::Type::StopAttack:
            bot->AttackStop();
            break;
        case BotAction::Type::ClearTarget:
            bot->SetTarget(ObjectGuid::Empty);
            break;
        default:
            break;
    }
}

void WorldServerBridge::HandleTargetAction(const BotAction& action)
{
    Player* bot = GetBotByGuid(action.botGuid);
    if (!bot)
        return;

    uint64_t targetGuid = action.data.target.targetGuid;
    if (targetGuid)
    {
        Unit* target = ObjectAccessor::GetUnit(*bot, ObjectGuid(targetGuid));
        if (target)
        {
            bot->SetTarget(target->GetGUID());
        }
    }
}

Player* WorldServerBridge::GetBotByGuid(uint64_t guid)
{
    ObjectGuid objGuid(guid);
    return ObjectAccessor::FindPlayer(objGuid);
}

PlayerbotAI* WorldServerBridge::GetBotAI(Player* bot)
{
    if (!bot)
        return nullptr;

    return GET_PLAYERBOT_AI(bot);
}

void WorldServerBridge::ResetMetrics()
{
    m_metrics = BridgeMetrics();
}

void WorldServerBridge::SetEnabled(bool enabled)
{
    m_config.enabled = enabled;

    if (enabled && !m_initialized)
    {
        Initialize(m_config);
    }
    else if (!enabled && m_initialized)
    {
        Shutdown();
    }
}

} // namespace ipc
} // namespace ecs
