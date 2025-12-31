/*
 * Bot Engine - Standalone process for bot AI execution
 *
 * This is the external process that runs bot AI logic, communicating
 * with the worldserver via shared memory IPC.
 *
 * Architecture:
 * - Receives entity updates from worldserver via ring buffer
 * - Maintains local ECS registry for AI processing
 * - Sends action requests back to worldserver via ring buffer
 * - Runs at higher frequency than main server loop
 */

#ifndef _BOT_ENGINE_H
#define _BOT_ENGINE_H

#include <cstdint>
#include <atomic>
#include <thread>
#include <string>
#include <vector>
#include <unordered_map>
#include <functional>

// Forward declare IPC types (included in .cpp)
namespace ecs { namespace ipc {
    struct EntityUpdate;
    struct BotAction;
    struct EntitySnapshot;
}}

namespace botengine {

/*
 * Engine configuration
 */
struct EngineConfig
{
    std::string shmName = "swarm_bots";
    uint32_t tickRateHz = 20;              // AI ticks per second
    uint32_t heartbeatIntervalMs = 1000;   // Heartbeat update interval
    uint32_t reconnectDelayMs = 5000;      // Delay before reconnect attempt
    uint32_t maxBotsPerTick = 1000;        // Max bots to process per tick
    bool enableMetrics = true;
};

/*
 * Engine metrics
 */
struct EngineMetrics
{
    std::atomic<uint64_t> ticksProcessed{0};
    std::atomic<uint64_t> updatesReceived{0};
    std::atomic<uint64_t> actionsSent{0};
    std::atomic<uint64_t> botsActive{0};
    std::atomic<uint64_t> lastTickTimeUs{0};
    std::atomic<uint64_t> avgTickTimeUs{0};
    std::atomic<uint64_t> maxTickTimeUs{0};
};

/*
 * Local bot state for AI processing
 */
struct LocalBotState
{
    uint64_t guid = 0;
    uint64_t lastUpdate = 0;

    // Position
    float x = 0, y = 0, z = 0, orientation = 0;
    uint32_t mapId = 0;

    // Vitals
    uint32_t health = 0, maxHealth = 0;
    uint32_t power = 0, maxPower = 0;

    // State
    uint8_t combatFlags = 0;
    uint8_t classId = 0;
    uint8_t level = 0;
    uint8_t aiState = 0;

    // Target
    uint64_t targetGuid = 0;

    // AI-specific data
    uint32_t currentBehavior = 0;
    uint32_t behaviorTimer = 0;
    uint64_t squadId = 0;
};

/*
 * BotEngine - Main engine class
 */
class BotEngine
{
public:
    BotEngine();
    ~BotEngine();

    // Lifecycle
    bool Initialize(const EngineConfig& config);
    void Run();
    void RequestShutdown();
    bool IsRunning() const { return m_running; }

    // Bot management
    size_t GetBotCount() const { return m_bots.size(); }
    LocalBotState* GetBot(uint64_t guid);
    const EngineMetrics& GetMetrics() const { return m_metrics; }

    // AI callback registration
    using AICallback = std::function<void(LocalBotState& bot, float deltaTime)>;
    void RegisterAICallback(AICallback callback) { m_aiCallbacks.push_back(callback); }

private:
    // Core loop
    void ProcessTick(float deltaTime);
    void ProcessUpdates();
    void ProcessAI(float deltaTime);
    void FlushActions();

    // IPC handlers
    void HandleEntityUpdate(const ecs::ipc::EntityUpdate& update);
    void HandlePositionUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update);
    void HandleVitalsUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update);
    void HandleCombatUpdate(uint64_t guid, const ecs::ipc::EntityUpdate& update);
    void HandleEntitySpawn(uint64_t guid, const ecs::ipc::EntityUpdate& update);
    void HandleEntityDespawn(uint64_t guid);

    // Action sending
    void SendMoveAction(uint64_t botGuid, float x, float y, float z, uint32_t mapId);
    void SendCastAction(uint64_t botGuid, uint32_t spellId, uint64_t targetGuid);
    void SendAttackAction(uint64_t botGuid, uint64_t targetGuid);

    // State
    EngineConfig m_config;
    EngineMetrics m_metrics;
    std::atomic<bool> m_running{false};
    std::atomic<bool> m_connected{false};

    // Bot storage
    std::unordered_map<uint64_t, LocalBotState> m_bots;
    std::vector<uint64_t> m_activeBotGuids;  // For iteration

    // AI callbacks
    std::vector<AICallback> m_aiCallbacks;

    // Pending actions
    std::vector<ecs::ipc::BotAction> m_pendingActions;
};

} // namespace botengine

#endif // _BOT_ENGINE_H
