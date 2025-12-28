/*
 * BotRegistry - Singleton manager bridging ECS with existing bot system
 *
 * This is the central integration point between the new ECS architecture
 * and the existing PlayerbotAI system. It allows incremental migration
 * by maintaining both systems simultaneously.
 *
 * Responsibilities:
 * - Owns the ECS Registry
 * - Maps between WoW GUIDs and ECS EntityIds
 * - Coordinates state synchronization
 * - Provides batch update interface
 */

#ifndef _PLAYERBOT_ECS_BOT_REGISTRY_H
#define _PLAYERBOT_ECS_BOT_REGISTRY_H

#include "Types.h"
#include "Registry.h"
#include "Components.h"
#include <unordered_map>
#include <mutex>
#include <functional>

class PlayerbotAI;
class Player;

namespace ecs {

/*
 * BotRegistry - Central bot management with ECS
 */
class BotRegistry
{
public:
    // Singleton access
    static BotRegistry& Instance()
    {
        static BotRegistry instance;
        return instance;
    }

    // Non-copyable
    BotRegistry(const BotRegistry&) = delete;
    BotRegistry& operator=(const BotRegistry&) = delete;

    /*
     * Initialize the registry with expected bot count
     */
    void Initialize(size_t expectedBotCount = 10000);

    /*
     * Shutdown and cleanup
     */
    void Shutdown();

    /*
     * Register a bot with the ECS
     * Creates entity and adds BotLink component
     * Returns the new EntityId
     */
    EntityId RegisterBot(PlayerbotAI* botAI, Player* player);

    /*
     * Unregister a bot from the ECS
     * Destroys entity and removes from GUID map
     */
    void UnregisterBot(EntityId entity);
    void UnregisterBot(uint64_t playerGuid);

    /*
     * Lookup entity by player GUID
     */
    EntityId GetEntityByGuid(uint64_t playerGuid) const;

    /*
     * Check if bot is registered
     */
    bool IsRegistered(uint64_t playerGuid) const;
    bool IsRegistered(EntityId entity) const;

    /*
     * Get bot count
     */
    size_t GetBotCount() const { return m_guidToEntity.size(); }

    /*
     * Direct registry access for systems
     */
    Registry& GetRegistry() { return m_registry; }
    const Registry& GetRegistry() const { return m_registry; }

    /*
     * Sync state from WoW objects to ECS components
     * Should be called before batch updates
     */
    void SyncFromWoW();

    /*
     * Sync specific entity from WoW state
     */
    void SyncEntityFromWoW(EntityId entity);

    /*
     * Batch iterate over all bots with callback
     * Callback: void(EntityId, BotLink&, Position&, ...)
     */
    template<typename Func>
    void ForEachBot(Func&& func)
    {
        m_registry.ForEach<BotLink>([&](EntityId id, BotLink& link) {
            func(id, link);
        });
    }

    /*
     * Iterate bots that have specific components
     */
    template<typename... Components, typename Func>
    void ForEachBotWith(Func&& func)
    {
        for (auto [id, link] : View<BotLink>(m_registry))
        {
            if (m_registry.HasComponents<Components...>(id))
            {
                func(id, link, *m_registry.GetComponent<Components>(id)...);
            }
        }
    }

    /*
     * Update metrics
     */
    struct Metrics
    {
        uint32_t totalBots = 0;
        uint32_t botsInCombat = 0;
        uint32_t botsMoving = 0;
        uint32_t botsByMap[1000] = {0};   // Count per map
        float avgSyncTimeMs = 0.0f;
        float avgUpdateTimeMs = 0.0f;
        uint32_t lastUpdateTime = 0;
    };

    const Metrics& GetMetrics() const { return m_metrics; }
    void UpdateMetrics();

private:
    BotRegistry() = default;
    ~BotRegistry() = default;

    // Core ECS registry
    Registry m_registry;

    // GUID to Entity mapping
    std::unordered_map<uint64_t, EntityId> m_guidToEntity;

    // Performance metrics
    Metrics m_metrics;

    // Initialization flag
    bool m_initialized = false;
};

/*
 * SyncSystem - Synchronizes WoW state to ECS components
 *
 * This system reads current game state and updates ECS components.
 * It should be run at the start of each update cycle.
 */
class SyncSystem
{
public:
    /*
     * Sync position from Player to Position component
     */
    static void SyncPosition(Player* player, Position& pos);

    /*
     * Sync health/power from Player to Health/Power components
     */
    static void SyncVitals(Player* player, Health& health, Power& power);

    /*
     * Sync combat state from Player to CombatState component
     */
    static void SyncCombatState(Player* player, CombatState& combat);

    /*
     * Sync stats from Player to Stats component
     */
    static void SyncStats(Player* player, Stats& stats);

    /*
     * Full sync of all components for an entity
     */
    static void SyncAll(EntityId entity, Registry& registry);
};

/*
 * Convenience macro for accessing the bot registry
 */
#define sBotRegistry ecs::BotRegistry::Instance()

} // namespace ecs

#endif // _PLAYERBOT_ECS_BOT_REGISTRY_H
