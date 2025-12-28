/*
 * ECS Benchmark Implementation
 */

#include "Benchmark.h"
#include "Timer.h"
#include "Log.h"
#include <random>
#include <algorithm>
#include <cstring>

namespace ecs {

// =============================================================================
// ScopedTimer
// =============================================================================

ScopedTimer::ScopedTimer(float& outMs)
    : m_outMs(outMs), m_startTime(getMSTime())
{
}

ScopedTimer::~ScopedTimer()
{
    m_outMs = static_cast<float>(getMSTimeDiff(m_startTime, getMSTime()));
}

// =============================================================================
// Benchmark
// =============================================================================

std::vector<BenchmarkResult> Benchmark::RunAll(uint32_t entityCount, uint32_t iterations)
{
    LOG_INFO("playerbots", "ECS Benchmark: Starting with {} entities, {} iterations",
             entityCount, iterations);

    std::vector<BenchmarkResult> results;

    results.push_back(BenchmarkEntityLifecycle(entityCount, iterations));
    results.push_back(BenchmarkComponentOperations(entityCount, iterations));
    results.push_back(BenchmarkSingleComponentIteration(entityCount, iterations));
    results.push_back(BenchmarkMultiComponentIteration(entityCount, iterations));
    results.push_back(BenchmarkPositionSync(entityCount, iterations));
    results.push_back(BenchmarkSpatialQuery(entityCount, 1000));

    LogResults(results);

    return results;
}

BenchmarkResult Benchmark::BenchmarkEntityLifecycle(uint32_t count, uint32_t iterations)
{
    BenchmarkResult result;
    result.name = "Entity Lifecycle (create/destroy)";
    result.entityCount = count;
    result.iterations = iterations;
    result.minMs = std::numeric_limits<float>::max();
    result.maxMs = 0.0f;

    for (uint32_t iter = 0; iter < iterations; ++iter)
    {
        Registry registry;
        registry.RegisterComponent<Position>();
        registry.RegisterComponent<Health>();
        registry.Reserve(count);

        std::vector<EntityId> entities;
        entities.reserve(count);

        float iterMs = 0.0f;
        {
            ScopedTimer timer(iterMs);

            // Create entities
            for (uint32_t i = 0; i < count; ++i)
            {
                EntityId id = registry.CreateEntity(EntityType::Bot);
                registry.AddComponent<Position>(id);
                registry.AddComponent<Health>(id);
                entities.push_back(id);
            }

            // Destroy all entities
            for (EntityId id : entities)
            {
                registry.DestroyEntity(id);
            }
        }

        result.totalMs += iterMs;
        result.minMs = std::min(result.minMs, iterMs);
        result.maxMs = std::max(result.maxMs, iterMs);
    }

    result.avgPerIterationMs = result.totalMs / iterations;
    result.avgPerEntityUs = (result.avgPerIterationMs * 1000.0f) / (count * 2); // *2 for create+destroy

    return result;
}

BenchmarkResult Benchmark::BenchmarkComponentOperations(uint32_t entityCount, uint32_t iterations)
{
    BenchmarkResult result;
    result.name = "Component Add/Remove";
    result.entityCount = entityCount;
    result.iterations = iterations;
    result.minMs = std::numeric_limits<float>::max();

    Registry registry;
    registry.RegisterComponent<Position>();
    registry.RegisterComponent<Health>();
    registry.RegisterComponent<CombatState>();
    registry.Reserve(entityCount);

    // Pre-create entities
    std::vector<EntityId> entities;
    entities.reserve(entityCount);
    for (uint32_t i = 0; i < entityCount; ++i)
    {
        entities.push_back(registry.CreateEntity(EntityType::Bot));
    }

    for (uint32_t iter = 0; iter < iterations; ++iter)
    {
        float iterMs = 0.0f;
        {
            ScopedTimer timer(iterMs);

            // Add components
            for (EntityId id : entities)
            {
                registry.AddComponent<Position>(id);
                registry.AddComponent<Health>(id);
            }

            // Remove components
            for (EntityId id : entities)
            {
                registry.RemoveComponent<Position>(id);
                registry.RemoveComponent<Health>(id);
            }
        }

        result.totalMs += iterMs;
        result.minMs = std::min(result.minMs, iterMs);
        result.maxMs = std::max(result.maxMs, iterMs);
    }

    result.avgPerIterationMs = result.totalMs / iterations;
    result.avgPerEntityUs = (result.avgPerIterationMs * 1000.0f) / (entityCount * 4); // 4 ops per entity

    return result;
}

BenchmarkResult Benchmark::BenchmarkSingleComponentIteration(uint32_t entityCount, uint32_t iterations)
{
    BenchmarkResult result;
    result.name = "Single Component Iteration";
    result.entityCount = entityCount;
    result.iterations = iterations;
    result.minMs = std::numeric_limits<float>::max();

    Registry registry;
    registry.RegisterComponent<Position>();
    registry.Reserve(entityCount);

    // Create entities with positions
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dist(-1000.0f, 1000.0f);

    for (uint32_t i = 0; i < entityCount; ++i)
    {
        EntityId id = registry.CreateEntity(EntityType::Bot);
        Position& pos = registry.AddComponent<Position>(id);
        pos.x = dist(gen);
        pos.y = dist(gen);
        pos.z = dist(gen);
    }

    volatile float sum = 0.0f; // Prevent optimization

    for (uint32_t iter = 0; iter < iterations; ++iter)
    {
        float iterMs = 0.0f;
        {
            ScopedTimer timer(iterMs);

            registry.ForEach<Position>([&sum](EntityId id, Position& pos) {
                // Simple operation to prevent optimization
                sum += pos.x + pos.y + pos.z;
                pos.x += 0.001f;
            });
        }

        result.totalMs += iterMs;
        result.minMs = std::min(result.minMs, iterMs);
        result.maxMs = std::max(result.maxMs, iterMs);
    }

    result.avgPerIterationMs = result.totalMs / iterations;
    result.avgPerEntityUs = (result.avgPerIterationMs * 1000.0f) / entityCount;

    return result;
}

BenchmarkResult Benchmark::BenchmarkMultiComponentIteration(uint32_t entityCount, uint32_t iterations)
{
    BenchmarkResult result;
    result.name = "Multi-Component Iteration (3 components)";
    result.entityCount = entityCount;
    result.iterations = iterations;
    result.minMs = std::numeric_limits<float>::max();

    Registry registry;
    registry.RegisterComponent<Position>();
    registry.RegisterComponent<Velocity>();
    registry.RegisterComponent<Health>();
    registry.Reserve(entityCount);

    // Create entities with all components
    for (uint32_t i = 0; i < entityCount; ++i)
    {
        EntityId id = registry.CreateEntity(EntityType::Bot);
        Position& pos = registry.AddComponent<Position>(id);
        Velocity& vel = registry.AddComponent<Velocity>(id);
        Health& health = registry.AddComponent<Health>(id);

        pos.x = static_cast<float>(i % 1000);
        pos.y = static_cast<float>(i / 1000);
        vel.dx = 1.0f;
        vel.dy = 0.0f;
        vel.isMoving = true;
        health.current = 100;
        health.max = 100;
    }

    volatile float sum = 0.0f;

    for (uint32_t iter = 0; iter < iterations; ++iter)
    {
        float iterMs = 0.0f;
        {
            ScopedTimer timer(iterMs);

            // Use View for multi-component iteration
            for (auto [id, pos, vel, health] : View<Position, Velocity, Health>(registry))
            {
                pos.x += vel.dx;
                pos.y += vel.dy;
                sum += health.Percent();
            }
        }

        result.totalMs += iterMs;
        result.minMs = std::min(result.minMs, iterMs);
        result.maxMs = std::max(result.maxMs, iterMs);
    }

    result.avgPerIterationMs = result.totalMs / iterations;
    result.avgPerEntityUs = (result.avgPerIterationMs * 1000.0f) / entityCount;

    return result;
}

BenchmarkResult Benchmark::BenchmarkPositionSync(uint32_t entityCount, uint32_t iterations)
{
    BenchmarkResult result;
    result.name = "Position Sync (simulated)";
    result.entityCount = entityCount;
    result.iterations = iterations;
    result.minMs = std::numeric_limits<float>::max();

    Registry registry;
    registry.RegisterComponent<Position>();
    registry.Reserve(entityCount);

    // Create entities
    for (uint32_t i = 0; i < entityCount; ++i)
    {
        EntityId id = registry.CreateEntity(EntityType::Bot);
        registry.AddComponent<Position>(id);
    }

    // Simulated source data (as if reading from Player objects)
    std::vector<float> sourceX(entityCount);
    std::vector<float> sourceY(entityCount);
    std::vector<float> sourceZ(entityCount);

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dist(-5000.0f, 5000.0f);

    for (uint32_t i = 0; i < entityCount; ++i)
    {
        sourceX[i] = dist(gen);
        sourceY[i] = dist(gen);
        sourceZ[i] = dist(gen);
    }

    for (uint32_t iter = 0; iter < iterations; ++iter)
    {
        // Update source data to simulate movement
        for (uint32_t i = 0; i < entityCount; ++i)
        {
            sourceX[i] += 0.1f;
        }

        float iterMs = 0.0f;
        {
            ScopedTimer timer(iterMs);

            // Direct array access for maximum efficiency
            ComponentArray<Position>* positions = registry.GetComponentArray<Position>();
            Position* data = positions->Data();
            size_t count = positions->Size();

            for (size_t i = 0; i < count; ++i)
            {
                data[i].x = sourceX[i];
                data[i].y = sourceY[i];
                data[i].z = sourceZ[i];

                // Compute cell
                constexpr float CELL_SIZE = 32.0f;
                data[i].cellX = static_cast<int32_t>(data[i].x / CELL_SIZE);
                data[i].cellY = static_cast<int32_t>(data[i].y / CELL_SIZE);
            }
        }

        result.totalMs += iterMs;
        result.minMs = std::min(result.minMs, iterMs);
        result.maxMs = std::max(result.maxMs, iterMs);
    }

    result.avgPerIterationMs = result.totalMs / iterations;
    result.avgPerEntityUs = (result.avgPerIterationMs * 1000.0f) / entityCount;

    return result;
}

BenchmarkResult Benchmark::BenchmarkSpatialQuery(uint32_t entityCount, uint32_t queryCount)
{
    BenchmarkResult result;
    result.name = "Spatial Query (find nearby)";
    result.entityCount = entityCount;
    result.iterations = queryCount;
    result.minMs = std::numeric_limits<float>::max();

    Registry registry;
    registry.RegisterComponent<Position>();
    registry.Reserve(entityCount);

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> dist(-2000.0f, 2000.0f);

    // Create entities spread across the world
    for (uint32_t i = 0; i < entityCount; ++i)
    {
        EntityId id = registry.CreateEntity(EntityType::Bot);
        Position& pos = registry.AddComponent<Position>(id);
        pos.x = dist(gen);
        pos.y = dist(gen);
        pos.z = 0.0f;
        pos.mapId = 0;

        constexpr float CELL_SIZE = 32.0f;
        pos.cellX = static_cast<int32_t>(pos.x / CELL_SIZE);
        pos.cellY = static_cast<int32_t>(pos.y / CELL_SIZE);
    }

    // Build spatial index
    SpatialUpdateSystem::RebuildIndex(registry);

    // Random query positions
    std::vector<float> queryX(queryCount);
    std::vector<float> queryY(queryCount);
    for (uint32_t i = 0; i < queryCount; ++i)
    {
        queryX[i] = dist(gen);
        queryY[i] = dist(gen);
    }

    volatile size_t totalFound = 0;

    float iterMs = 0.0f;
    {
        ScopedTimer timer(iterMs);

        for (uint32_t i = 0; i < queryCount; ++i)
        {
            auto nearby = SpatialUpdateSystem::FindNearby(
                registry, queryX[i], queryY[i], 0.0f, 0, 50.0f);
            totalFound += nearby.size();
        }
    }

    result.totalMs = iterMs;
    result.avgPerIterationMs = iterMs / queryCount;
    result.avgPerEntityUs = (iterMs * 1000.0f) / queryCount;  // Per query, not per entity
    result.minMs = result.avgPerIterationMs;
    result.maxMs = result.avgPerIterationMs;

    return result;
}

size_t Benchmark::EstimateMemoryPerEntity()
{
    // Calculate size of all components that would be attached to a typical bot
    size_t total = 0;

    total += sizeof(Position);
    total += sizeof(Velocity);
    total += sizeof(PathState);
    total += sizeof(Health);
    total += sizeof(Power);
    total += sizeof(Stats);
    total += sizeof(Target);
    total += sizeof(ThreatList);
    total += sizeof(CombatState);
    total += sizeof(Cooldowns);
    total += sizeof(AIState);
    total += sizeof(BotRole);
    total += sizeof(SquadMember);
    total += sizeof(BotLink);
    total += sizeof(Dirty);
    total += sizeof(Timers);

    // Add overhead for sparse set storage (approximately)
    // Each component array needs entity->index mapping
    total += 16 * sizeof(size_t);  // 16 component types * map entry overhead

    return total;
}

void Benchmark::LogResults(const std::vector<BenchmarkResult>& results)
{
    LOG_INFO("playerbots", "");
    LOG_INFO("playerbots", "=== ECS Benchmark Results ===");
    LOG_INFO("playerbots", "");

    for (const auto& r : results)
    {
        LOG_INFO("playerbots", "{}", r.name);
        LOG_INFO("playerbots", "  Entities: {}, Iterations: {}", r.entityCount, r.iterations);
        LOG_INFO("playerbots", "  Total: {:.2f}ms, Avg/iter: {:.3f}ms", r.totalMs, r.avgPerIterationMs);
        LOG_INFO("playerbots", "  Per entity: {:.3f}us, Min: {:.3f}ms, Max: {:.3f}ms",
                 r.avgPerEntityUs, r.minMs, r.maxMs);
        LOG_INFO("playerbots", "");
    }

    size_t memPerEntity = EstimateMemoryPerEntity();
    LOG_INFO("playerbots", "Memory Estimate:");
    LOG_INFO("playerbots", "  Per entity: {} bytes ({:.1f} KB)",
             memPerEntity, memPerEntity / 1024.0f);
    LOG_INFO("playerbots", "  10,000 bots: {:.1f} MB", (memPerEntity * 10000) / (1024.0f * 1024.0f));
    LOG_INFO("playerbots", "  100,000 bots: {:.1f} MB", (memPerEntity * 100000) / (1024.0f * 1024.0f));
    LOG_INFO("playerbots", "");
}

void Benchmark::CompareWithBaseline(const std::vector<BenchmarkResult>& ecsResults)
{
    // Baseline estimates from current OOP system (approximate)
    // These would need to be measured separately
    LOG_INFO("playerbots", "=== Comparison with OOP Baseline ===");
    LOG_INFO("playerbots", "");
    LOG_INFO("playerbots", "Current OOP system estimates:");
    LOG_INFO("playerbots", "  Memory per bot: 25-70 KB (vs ECS: {:.1f} KB)",
             EstimateMemoryPerEntity() / 1024.0f);
    LOG_INFO("playerbots", "  Iteration: Object pointer chasing (cache unfriendly)");
    LOG_INFO("playerbots", "  ECS advantage: Contiguous memory, SIMD-friendly");
    LOG_INFO("playerbots", "");
}

} // namespace ecs
