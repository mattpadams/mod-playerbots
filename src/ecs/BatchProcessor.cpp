/*
 * ECS Batch Processor Implementation
 */

#include "BatchProcessor.h"
#include "BotRegistry.h"
#include "Systems.h"
#include "Timer.h"
#include "Log.h"
#include <algorithm>

namespace ecs {

// =============================================================================
// StatePartition
// =============================================================================

void StatePartition::Rebuild(Registry& registry)
{
    uint32_t startTime = getMSTime();

    // Clear all partitions
    for (auto& partition : m_partitions)
    {
        partition.clear();
    }

    uint32_t totalEntities = 0;

    // Iterate all entities with AIState and partition them
    registry.ForEach<AIState>([this, &totalEntities](EntityId id, AIState& ai) {
        size_t stateIndex = static_cast<size_t>(ai.currentState);
        if (stateIndex < STATE_COUNT)
        {
            m_partitions[stateIndex].push_back(id);
            totalEntities++;
        }
    });

    // Update statistics
    m_stats.totalEntities = totalEntities;
    m_stats.rebuildTimeMs = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));

    for (size_t i = 0; i < STATE_COUNT; ++i)
    {
        m_stats.countPerState[i] = static_cast<uint32_t>(m_partitions[i].size());
    }
}

// =============================================================================
// UpdateScheduler
// =============================================================================

uint16_t UpdateScheduler::GetIntervalForState(AIState::State state) const
{
    switch (state)
    {
        case AIState::State::Combat:    return m_config.combatIntervalMs;
        case AIState::State::Following: return m_config.followingIntervalMs;
        case AIState::State::Traveling: return m_config.travelingIntervalMs;
        case AIState::State::Idle:      return m_config.idleIntervalMs;
        case AIState::State::Resting:   return m_config.restingIntervalMs;
        case AIState::State::Dead:      return m_config.deadIntervalMs;
        case AIState::State::Looting:   return m_config.combatIntervalMs;  // Looting needs responsiveness
        case AIState::State::Trading:   return m_config.idleIntervalMs;
        default:                        return m_config.idleIntervalMs;
    }
}

bool UpdateScheduler::NeedsUpdate(const AIState& ai, uint32_t now) const
{
    return now >= ai.nextUpdateTime;
}

std::vector<EntityId> UpdateScheduler::FilterNeedingUpdate(
    Registry& registry,
    const std::vector<EntityId>& entities,
    uint32_t now) const
{
    std::vector<EntityId> result;
    result.reserve(entities.size() / 2);  // Estimate half need updates

    for (EntityId id : entities)
    {
        if (const AIState* ai = registry.GetComponent<AIState>(id))
        {
            if (NeedsUpdate(*ai, now))
            {
                result.push_back(id);
            }
        }
    }

    return result;
}

size_t UpdateScheduler::GetPendingCount(Registry& registry, AIState::State state, uint32_t now) const
{
    size_t count = 0;

    registry.ForEach<AIState>([&](EntityId id, AIState& ai) {
        if (ai.currentState == state && NeedsUpdate(ai, now))
        {
            count++;
        }
    });

    return count;
}

// =============================================================================
// ParallelExecutor
// =============================================================================

void ParallelExecutor::Initialize(size_t threadCount)
{
    if (m_initialized)
        return;

    if (threadCount == 0)
    {
        threadCount = std::thread::hardware_concurrency();
        if (threadCount == 0)
            threadCount = 4;  // Fallback
    }

    // Cap at reasonable number
    m_threadCount = std::min(threadCount, static_cast<size_t>(16));

    LOG_INFO("playerbots", "ECS ParallelExecutor: Initialized with {} threads", m_threadCount);
    m_initialized = true;
}

void ParallelExecutor::Shutdown()
{
    m_initialized = false;
}

void ParallelExecutor::ExecuteParallel(std::vector<std::function<void()>>& tasks)
{
    if (tasks.empty())
        return;

    if (tasks.size() == 1 || m_threadCount <= 1)
    {
        // Single-threaded execution
        for (auto& task : tasks)
        {
            task();
        }
        return;
    }

    std::atomic<size_t> nextTask{0};

    auto worker = [&]() {
        while (true)
        {
            size_t idx = nextTask.fetch_add(1);
            if (idx >= tasks.size())
                break;
            tasks[idx]();
        }
    };

    std::vector<std::thread> threads;
    threads.reserve(m_threadCount - 1);

    for (size_t i = 1; i < m_threadCount && i < tasks.size(); ++i)
    {
        threads.emplace_back(worker);
    }

    // Main thread participates
    worker();

    for (auto& t : threads)
    {
        t.join();
    }
}

// =============================================================================
// BatchProcessor
// =============================================================================

void BatchProcessor::Initialize(size_t threadCount)
{
    m_executor.Initialize(threadCount);
    LOG_INFO("playerbots", "ECS BatchProcessor: Initialized");
}

void BatchProcessor::Shutdown()
{
    m_executor.Shutdown();
}

void BatchProcessor::ProcessBatch(Registry& registry, uint32_t now, float deltaTime)
{
    uint32_t startTime = getMSTime();

    // Rebuild partitions periodically
    if (now - m_lastPartitionRebuild >= PARTITION_REBUILD_INTERVAL)
    {
        uint32_t partitionStart = getMSTime();
        m_partition.Rebuild(registry);
        m_stats.partitionTimeMs = static_cast<float>(getMSTimeDiff(partitionStart, getMSTime()));
        m_lastPartitionRebuild = now;
    }

    m_stats.totalProcessed = 0;
    m_stats.combatProcessed = 0;
    m_stats.idleProcessed = 0;
    m_stats.skippedThisTick = 0;

    // Process combat bots first (highest priority, every tick)
    {
        uint32_t combatStart = getMSTime();
        ProcessStateGroup(registry, AIState::State::Combat, now, deltaTime);
        m_stats.combatTimeMs = static_cast<float>(getMSTimeDiff(combatStart, getMSTime()));
    }

    // Process following bots
    ProcessStateGroup(registry, AIState::State::Following, now, deltaTime);

    // Process traveling bots
    ProcessStateGroup(registry, AIState::State::Traveling, now, deltaTime);

    // Process looting bots (needs responsiveness)
    ProcessStateGroup(registry, AIState::State::Looting, now, deltaTime);

    // Process idle bots (lower priority)
    {
        uint32_t idleStart = getMSTime();
        ProcessStateGroup(registry, AIState::State::Idle, now, deltaTime);
        m_stats.idleTimeMs = static_cast<float>(getMSTimeDiff(idleStart, getMSTime()));
    }

    // Process resting bots
    ProcessStateGroup(registry, AIState::State::Resting, now, deltaTime);

    // Dead bots rarely need updates
    ProcessStateGroup(registry, AIState::State::Dead, now, deltaTime);

    m_stats.totalTimeMs = static_cast<float>(getMSTimeDiff(startTime, getMSTime()));
}

void BatchProcessor::ProcessStateGroup(
    Registry& registry,
    AIState::State state,
    uint32_t now,
    [[maybe_unused]] float deltaTime)
{
    const auto& entities = m_partition.GetEntitiesInState(state);
    if (entities.empty())
        return;

    // Filter to only entities needing update
    auto toUpdate = m_scheduler.FilterNeedingUpdate(registry, entities, now);

    m_stats.skippedThisTick += static_cast<uint32_t>(entities.size() - toUpdate.size());

    if (toUpdate.empty())
        return;

    // Get update interval for this state
    uint16_t interval = m_scheduler.GetIntervalForState(state);

    // Process each entity that needs an update
    // For combat bots with enough entities, consider parallel processing
    if (state == AIState::State::Combat && toUpdate.size() > 100 && m_executor.GetThreadCount() > 1)
    {
        // Parallel processing for large combat groups
        // Note: This requires thread-safe access to game state
        // For now, process sequentially but in batches
        for (EntityId id : toUpdate)
        {
            if (AIState* ai = registry.GetComponent<AIState>(id))
            {
                ai->lastUpdateTime = now;
                ai->nextUpdateTime = now + interval;

                // The actual AI update is still handled by the existing system
                // This just manages the scheduling
            }
        }
        m_stats.combatProcessed += static_cast<uint32_t>(toUpdate.size());
    }
    else
    {
        // Sequential processing
        for (EntityId id : toUpdate)
        {
            if (AIState* ai = registry.GetComponent<AIState>(id))
            {
                ai->lastUpdateTime = now;
                ai->nextUpdateTime = now + interval;
            }
        }

        if (state == AIState::State::Idle)
        {
            m_stats.idleProcessed += static_cast<uint32_t>(toUpdate.size());
        }
    }

    m_stats.totalProcessed += static_cast<uint32_t>(toUpdate.size());
}

} // namespace ecs
