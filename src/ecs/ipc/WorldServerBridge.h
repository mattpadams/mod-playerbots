/*
 * WorldServer Bridge - IPC integration for worldserver
 *
 * Manages communication between worldserver and external bot-engine process.
 * Exports bot state updates and imports action requests.
 */

#ifndef _PLAYERBOT_ECS_IPC_WORLD_SERVER_BRIDGE_H
#define _PLAYERBOT_ECS_IPC_WORLD_SERVER_BRIDGE_H

#include "SharedMemory.h"
#include "../Components.h"
#include <vector>
#include <chrono>

class Player;
class Unit;
class PlayerbotAI;

namespace ecs {
namespace ipc {

/*
 * BridgeConfig - Configuration for the worldserver bridge
 */
struct BridgeConfig
{
    std::string shmName = "swarm_bots";
    bool enabled = false;
    uint32_t exportIntervalMs = 50;      // How often to batch export updates
    uint32_t heartbeatIntervalMs = 1000; // Heartbeat update frequency
    uint32_t actionPollIntervalMs = 10;  // How often to check for actions
    size_t maxUpdatesPerTick = 1000;     // Max updates to send per export tick
};

/*
 * BridgeMetrics - Statistics for monitoring
 */
struct BridgeMetrics
{
    uint64_t updatesExported = 0;
    uint64_t actionsImported = 0;
    uint64_t exportCalls = 0;
    uint64_t importCalls = 0;
    uint64_t lastExportTimeUs = 0;
    uint64_t lastImportTimeUs = 0;
    uint64_t droppedUpdates = 0;
    uint64_t failedActions = 0;
};

/*
 * WorldServerBridge - Main bridge class
 *
 * Singleton pattern, initialized during server startup if enabled.
 */
class WorldServerBridge
{
public:
    static WorldServerBridge& Instance()
    {
        static WorldServerBridge instance;
        return instance;
    }

    // Lifecycle
    bool Initialize(const BridgeConfig& config);
    void Shutdown();
    bool IsEnabled() const { return m_config.enabled && m_initialized; }
    bool IsConnected() const { return m_connected; }

    // Called from main update loop
    void Update(uint32_t diff);

    // Bot state export
    void ExportBotPosition(Player* bot);
    void ExportBotVitals(Player* bot);
    void ExportBotCombat(Player* bot);
    void ExportBotSpawn(Player* bot);
    void ExportBotDespawn(uint64_t guid);
    void ExportFullSnapshot(Player* bot);

    // Action processing
    void ProcessActions();

    // Metrics
    const BridgeMetrics& GetMetrics() const { return m_metrics; }
    void ResetMetrics();

    // Configuration
    const BridgeConfig& GetConfig() const { return m_config; }
    void SetEnabled(bool enabled);

private:
    WorldServerBridge() = default;

    // Main action dispatcher
    void HandleAction(const BotAction& action);

    // Action handlers
    void HandleMoveAction(const BotAction& action);
    void HandleCastAction(const BotAction& action);
    void HandleAttackAction(const BotAction& action);
    void HandleStopAction(const BotAction& action);
    void HandleTargetAction(const BotAction& action);

    // Helper to get bot by GUID
    Player* GetBotByGuid(uint64_t guid);
    PlayerbotAI* GetBotAI(Player* bot);

    // Queue pending updates
    void QueueUpdate(const EntityUpdate& update);
    void FlushUpdates();

    // State
    BridgeConfig m_config;
    BridgeMetrics m_metrics;
    bool m_initialized = false;
    bool m_connected = false;

    // Timing
    uint32_t m_exportTimer = 0;
    uint32_t m_actionTimer = 0;
    uint32_t m_heartbeatTimer = 0;
    std::chrono::steady_clock::time_point m_lastExportTime;

    // Pending updates queue
    std::vector<EntityUpdate> m_pendingUpdates;
};

#define sWorldServerBridge ecs::ipc::WorldServerBridge::Instance()

} // namespace ipc
} // namespace ecs

#endif // _PLAYERBOT_ECS_IPC_WORLD_SERVER_BRIDGE_H
