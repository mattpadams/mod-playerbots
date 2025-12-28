/*
 * ECS Batch Processor - State-based grouping and parallel processing
 *
 * Optimizations:
 * 1. State Partitioning - Group bots by AI state for cache-efficient processing
 * 2. Parallel Execution - Process independent systems/groups in parallel
 * 3. Update Scheduling - Skip bots that don't need updates this tick
 */

#ifndef _PLAYERBOT_ECS_BATCH_PROCESSOR_H
#define _PLAYERBOT_ECS_BATCH_PROCESSOR_H

#include "Types.h"
#include "Components.h"
#include "Registry.h"
#include <vector>
#include <array>
#include <thread>
#include <atomic>
#include <functional>
#include <mutex>

namespace ecs {

/*
 * StatePartition - Maintains lists of entities grouped by AI state
 *
 * Benefits:
 * - Process all combat bots together (hot path, needs frequent updates)
 * - Process idle bots less frequently (cold path)
 * - Better cache utilization when iterating similar bots
 */
class StatePartition
{
public:
    static constexpr size_t STATE_COUNT = 8;  // AIState::State enum count

    // Rebuild partitions from registry
    void Rebuild(Registry& registry);

    // Get entities in a specific state
    const std::vector<EntityId>& GetEntitiesInState(AIState::State state) const
    {
        return m_partitions[static_cast<size_t>(state)];
    }

    // Get count for a state
    size_t GetStateCount(AIState::State state) const
    {
        return m_partitions[static_cast<size_t>(state)].size();
    }

    // Quick access to common groups
    const std::vector<EntityId>& GetCombatBots() const { return GetEntitiesInState(AIState::State::Combat); }
    const std::vector<EntityId>& GetIdleBots() const { return GetEntitiesInState(AIState::State::Idle); }
    const std::vector<EntityId>& GetFollowingBots() const { return GetEntitiesInState(AIState::State::Following); }
    const std::vector<EntityId>& GetDeadBots() const { return GetEntitiesInState(AIState::State::Dead); }

    // Statistics
    struct Stats
    {
        uint32_t totalEntities = 0;
        uint32_t stateChanges = 0;
        float rebuildTimeMs = 0.0f;
        std::array<uint32_t, STATE_COUNT> countPerState = {};
    };

    const Stats& GetStats() const { return m_stats; }

private:
    std::array<std::vector<EntityId>, STATE_COUNT> m_partitions;
    Stats m_stats;
};

/*
 * UpdateScheduler - Determines which bots need updates this tick
 *
 * Different states have different update frequencies:
 * - Combat: Every tick (high priority)
 * - Following: Every 2-3 ticks
 * - Idle: Every 5-10 ticks
 * - Dead: Every 20+ ticks
 */
class UpdateScheduler
{
public:
    struct UpdateConfig
    {
        uint16_t combatIntervalMs = 100;      // 10 Hz
        uint16_t followingIntervalMs = 200;   // 5 Hz
        uint16_t travelingIntervalMs = 250;   // 4 Hz
        uint16_t idleIntervalMs = 500;        // 2 Hz
        uint16_t restingIntervalMs = 1000;    // 1 Hz
        uint16_t deadIntervalMs = 2000;       // 0.5 Hz
    };

    UpdateScheduler() = default;
    explicit UpdateScheduler(const UpdateConfig& config) : m_config(config) {}

    // Get interval for a state
    uint16_t GetIntervalForState(AIState::State state) const;

    // Check if entity needs update based on its state and timing
    bool NeedsUpdate(const AIState& ai, uint32_t now) const;

    // Filter entities that need updates this tick
    std::vector<EntityId> FilterNeedingUpdate(
        Registry& registry,
        const std::vector<EntityId>& entities,
        uint32_t now) const;

    // Get pending update count for a state
    size_t GetPendingCount(Registry& registry, AIState::State state, uint32_t now) const;

    const UpdateConfig& GetConfig() const { return m_config; }
    void SetConfig(const UpdateConfig& config) { m_config = config; }

private:
    UpdateConfig m_config;
};

/*
 * ParallelExecutor - Execute functions in parallel using thread pool
 *
 * For processing multiple entity groups simultaneously.
 */
class ParallelExecutor
{
public:
    // Initialize with thread count (0 = auto-detect)
    void Initialize(size_t threadCount = 0);
    void Shutdown();

    // Execute a function for each item in parallel
    template<typename T, typename Func>
    void ForEach(const std::vector<T>& items, Func&& func)
    {
        if (items.empty() || m_threadCount <= 1)
        {
            // Single-threaded fallback
            for (const auto& item : items)
            {
                func(item);
            }
            return;
        }

        // Partition work across threads
        size_t itemsPerThread = (items.size() + m_threadCount - 1) / m_threadCount;
        std::atomic<size_t> nextChunk{0};

        auto worker = [&]() {
            while (true)
            {
                size_t chunk = nextChunk.fetch_add(1);
                size_t start = chunk * itemsPerThread;
                if (start >= items.size())
                    break;

                size_t end = std::min(start + itemsPerThread, items.size());
                for (size_t i = start; i < end; ++i)
                {
                    func(items[i]);
                }
            }
        };

        // Launch workers
        std::vector<std::thread> threads;
        threads.reserve(m_threadCount - 1);

        for (size_t i = 1; i < m_threadCount; ++i)
        {
            threads.emplace_back(worker);
        }

        // Use main thread too
        worker();

        // Wait for completion
        for (auto& t : threads)
        {
            t.join();
        }
    }

    // Execute multiple independent tasks in parallel
    void ExecuteParallel(std::vector<std::function<void()>>& tasks);

    size_t GetThreadCount() const { return m_threadCount; }

private:
    size_t m_threadCount = 1;
    bool m_initialized = false;
};

/*
 * BatchProcessor - Main coordinator for optimized batch updates
 *
 * Combines state partitioning, scheduling, and parallel execution.
 */
class BatchProcessor
{
public:
    static BatchProcessor& Instance()
    {
        static BatchProcessor instance;
        return instance;
    }

    // Initialize the processor
    void Initialize(size_t threadCount = 0);
    void Shutdown();

    // Main update entry point
    void ProcessBatch(Registry& registry, uint32_t now, float deltaTime);

    // Process specific state group
    void ProcessStateGroup(
        Registry& registry,
        AIState::State state,
        uint32_t now,
        float deltaTime);

    // Get components
    StatePartition& GetPartition() { return m_partition; }
    UpdateScheduler& GetScheduler() { return m_scheduler; }
    ParallelExecutor& GetExecutor() { return m_executor; }

    // Statistics
    struct ProcessingStats
    {
        uint32_t totalProcessed = 0;
        uint32_t combatProcessed = 0;
        uint32_t idleProcessed = 0;
        uint32_t skippedThisTick = 0;
        float partitionTimeMs = 0.0f;
        float combatTimeMs = 0.0f;
        float idleTimeMs = 0.0f;
        float totalTimeMs = 0.0f;
    };

    const ProcessingStats& GetStats() const { return m_stats; }

private:
    BatchProcessor() = default;

    StatePartition m_partition;
    UpdateScheduler m_scheduler;
    ParallelExecutor m_executor;
    ProcessingStats m_stats;

    // Last partition rebuild time
    uint32_t m_lastPartitionRebuild = 0;
    static constexpr uint32_t PARTITION_REBUILD_INTERVAL = 1000;  // 1 second
};

#define sBatchProcessor ecs::BatchProcessor::Instance()

} // namespace ecs

#endif // _PLAYERBOT_ECS_BATCH_PROCESSOR_H
