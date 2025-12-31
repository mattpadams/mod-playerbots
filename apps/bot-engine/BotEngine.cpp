/*
 * Bot Engine Implementation
 */

#include "BotEngine.h"
#include "../../src/ecs/ipc/SharedMemory.h"

#include <chrono>
#include <iostream>
#include <cstring>

namespace botengine {

BotEngine::BotEngine()
{
}

BotEngine::~BotEngine()
{
    if (m_running)
    {
        RequestShutdown();
    }
}

bool BotEngine::Initialize(const EngineConfig& config)
{
    m_config = config;

    std::cout << "[BotEngine] Initializing with config:" << std::endl;
    std::cout << "  - SHM Name: " << config.shmName << std::endl;
    std::cout << "  - Tick Rate: " << config.tickRateHz << " Hz" << std::endl;
    std::cout << "  - Max Bots/Tick: " << config.maxBotsPerTick << std::endl;

    // Connect to shared memory
    if (!ecs::ipc::BotEngineIPC::Instance().InitializeClient(config.shmName))
    {
        std::cerr << "[BotEngine] Failed to connect to shared memory '"
                  << config.shmName << "'" << std::endl;
        return false;
    }

    m_connected = true;
    std::cout << "[BotEngine] Connected to shared memory" << std::endl;

    // Check if worldserver is alive
    if (!ecs::ipc::BotEngineIPC::Instance().IsPartnerAlive())
    {
        std::cerr << "[BotEngine] Warning: Worldserver heartbeat not detected" << std::endl;
    }

    m_running = true;
    return true;
}

void BotEngine::Run()
{
    using namespace std::chrono;

    const auto tickDuration = microseconds(1000000 / m_config.tickRateHz);
    auto lastTick = steady_clock::now();
    uint64_t tickTimeSum = 0;
    uint32_t tickCount = 0;

    std::cout << "[BotEngine] Starting main loop ("
              << m_config.tickRateHz << " Hz)" << std::endl;

    while (m_running)
    {
        auto tickStart = steady_clock::now();
        auto elapsed = duration_cast<microseconds>(tickStart - lastTick);
        float deltaTime = elapsed.count() / 1000000.0f;
        lastTick = tickStart;

        // Check connection
        if (!ecs::ipc::BotEngineIPC::Instance().IsPartnerAlive())
        {
            if (m_connected)
            {
                std::cerr << "[BotEngine] Lost connection to worldserver" << std::endl;
                m_connected = false;
            }

            // Wait before checking again
            std::this_thread::sleep_for(milliseconds(m_config.reconnectDelayMs));
            continue;
        }

        if (!m_connected)
        {
            std::cout << "[BotEngine] Reconnected to worldserver" << std::endl;
            m_connected = true;
        }

        // Process tick
        ProcessTick(deltaTime);

        // Update heartbeat
        ecs::ipc::BotEngineIPC::Instance().UpdateHeartbeat();

        // Calculate tick time
        auto tickEnd = steady_clock::now();
        auto tickTime = duration_cast<microseconds>(tickEnd - tickStart).count();
        m_metrics.lastTickTimeUs.store(tickTime, std::memory_order_relaxed);

        // Update average
        tickTimeSum += tickTime;
        ++tickCount;
        if (tickCount >= 100)
        {
            m_metrics.avgTickTimeUs.store(tickTimeSum / tickCount, std::memory_order_relaxed);
            tickTimeSum = 0;
            tickCount = 0;
        }

        // Update max
        uint64_t currentMax = m_metrics.maxTickTimeUs.load(std::memory_order_relaxed);
        if (static_cast<uint64_t>(tickTime) > currentMax)
        {
            m_metrics.maxTickTimeUs.store(tickTime, std::memory_order_relaxed);
        }

        m_metrics.ticksProcessed.fetch_add(1, std::memory_order_relaxed);

        // Sleep until next tick
        auto sleepDuration = tickDuration - duration_cast<microseconds>(tickEnd - tickStart);
        if (sleepDuration.count() > 0)
        {
            std::this_thread::sleep_for(sleepDuration);
        }
    }

    std::cout << "[BotEngine] Shutting down..." << std::endl;
    ecs::ipc::BotEngineIPC::Instance().Shutdown();
}

void BotEngine::RequestShutdown()
{
    m_running = false;
}

LocalBotState* BotEngine::GetBot(uint64_t guid)
{
    auto it = m_bots.find(guid);
    return it != m_bots.end() ? &it->second : nullptr;
}

void BotEngine::ProcessTick(float deltaTime)
{
    // 1. Receive updates from worldserver
    ProcessUpdates();

    // 2. Run AI on all bots
    ProcessAI(deltaTime);

    // 3. Send actions back to worldserver
    FlushActions();

    // Update bot count metric
    m_metrics.botsActive.store(m_bots.size(), std::memory_order_relaxed);
}

void BotEngine::ProcessUpdates()
{
    size_t count = ecs::ipc::BotEngineIPC::Instance().DrainUpdates(
        [](const ecs::ipc::EntityUpdate& update)
        {
            // Note: Can't use member function directly, need static dispatch
        }
    );

    // Alternative: manual drain
    // For now, we'll use the snapshot area instead of ring buffer for simplicity
    // The ring buffer is more for real-time position updates
}

void BotEngine::ProcessAI(float deltaTime)
{
    uint32_t processed = 0;

    for (auto& [guid, bot] : m_bots)
    {
        if (processed >= m_config.maxBotsPerTick)
            break;

        // Run all registered AI callbacks
        for (auto& callback : m_aiCallbacks)
        {
            callback(bot, deltaTime);
        }

        ++processed;
    }
}

void BotEngine::FlushActions()
{
    for (const auto& action : m_pendingActions)
    {
        if (!ecs::ipc::BotEngineIPC::Instance().SendAction(action))
        {
            // Action queue full, try again next tick
            break;
        }
        m_metrics.actionsSent.fetch_add(1, std::memory_order_relaxed);
    }
    m_pendingActions.clear();
}

void BotEngine::HandleEntityUpdate(const ecs::ipc::EntityUpdate& update)
{
    using Type = ecs::ipc::EntityUpdate::Type;

    m_metrics.updatesReceived.fetch_add(1, std::memory_order_relaxed);

    switch (update.type)
    {
        case Type::PositionUpdate:
            HandlePositionUpdate(update.entityGuid, update);
            break;
        case Type::VitalsUpdate:
            HandleVitalsUpdate(update.entityGuid, update);
            break;
        case Type::CombatStateUpdate:
            HandleCombatUpdate(update.entityGuid, update);
            break;
        case Type::EntitySpawn:
            HandleEntitySpawn(update.entityGuid, update);
            break;
        case Type::EntityDespawn:
            HandleEntityDespawn(update.entityGuid);
            break;
        default:
            break;
    }
}

void BotEngine::HandlePositionUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update)
{
    auto it = m_bots.find(guid);
    if (it == m_bots.end())
        return;

    auto& bot = it->second;
    bot.x = update.data.position.x;
    bot.y = update.data.position.y;
    bot.z = update.data.position.z;
    bot.orientation = update.data.position.orientation;
    bot.mapId = update.data.position.mapId;
    bot.lastUpdate = update.timestamp;
}

void BotEngine::HandleVitalsUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update)
{
    auto it = m_bots.find(guid);
    if (it == m_bots.end())
        return;

    auto& bot = it->second;
    bot.health = update.data.vitals.health;
    bot.maxHealth = update.data.vitals.maxHealth;
    bot.power = update.data.vitals.power;
    bot.maxPower = update.data.vitals.maxPower;
    bot.lastUpdate = update.timestamp;
}

void BotEngine::HandleCombatUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update)
{
    auto it = m_bots.find(guid);
    if (it == m_bots.end())
        return;

    auto& bot = it->second;
    bot.combatFlags = update.data.combat.combatFlags;
    bot.targetGuid = update.data.combat.targetGuid;
    bot.lastUpdate = update.timestamp;
}

void BotEngine::HandleEntitySpawn(uint64_t guid, const ecs::ipc::EntityUpdate& update)
{
    // Create or update bot
    LocalBotState& bot = m_bots[guid];
    bot.guid = guid;
    bot.lastUpdate = update.timestamp;

    // Add to active list if not present
    auto it = std::find(m_activeBotGuids.begin(), m_activeBotGuids.end(), guid);
    if (it == m_activeBotGuids.end())
    {
        m_activeBotGuids.push_back(guid);
    }
}

void BotEngine::HandleEntityDespawn(uint64_t guid)
{
    m_bots.erase(guid);

    // Remove from active list
    auto it = std::find(m_activeBotGuids.begin(), m_activeBotGuids.end(), guid);
    if (it != m_activeBotGuids.end())
    {
        m_activeBotGuids.erase(it);
    }
}

void BotEngine::SendMoveAction(uint64_t botGuid, float x, float y, float z, uint32_t mapId)
{
    ecs::ipc::BotAction action;
    action.botGuid = botGuid;
    action.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    action.type = ecs::ipc::BotAction::Type::MoveTo;
    action.priority = 1;
    action.data.moveTo.x = x;
    action.data.moveTo.y = y;
    action.data.moveTo.z = z;
    action.data.moveTo.mapId = mapId;

    m_pendingActions.push_back(action);
}

void BotEngine::SendCastAction(uint64_t botGuid, uint32_t spellId, uint64_t targetGuid)
{
    ecs::ipc::BotAction action;
    action.botGuid = botGuid;
    action.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    action.type = ecs::ipc::BotAction::Type::CastSpell;
    action.priority = 2;  // Higher priority for casts
    action.data.castSpell.spellId = spellId;
    action.data.castSpell.targetGuid = targetGuid;

    m_pendingActions.push_back(action);
}

void BotEngine::SendAttackAction(uint64_t botGuid, uint64_t targetGuid)
{
    ecs::ipc::BotAction action;
    action.botGuid = botGuid;
    action.timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    action.type = ecs::ipc::BotAction::Type::Attack;
    action.priority = 2;
    action.data.target.targetGuid = targetGuid;

    m_pendingActions.push_back(action);
}

} // namespace botengine
