/*
 * ECS Benchmark - Performance comparison tools
 *
 * Provides utilities to benchmark ECS performance against the
 * existing OOP system. Used to validate the ECS migration.
 */

#ifndef _PLAYERBOT_ECS_BENCHMARK_H
#define _PLAYERBOT_ECS_BENCHMARK_H

#include "ECS.h"
#include <string>
#include <vector>
#include <functional>

namespace ecs {

/*
 * BenchmarkResult - Results from a single benchmark run
 */
struct BenchmarkResult
{
    std::string name;
    uint32_t iterations = 0;
    uint32_t entityCount = 0;
    float totalMs = 0.0f;
    float avgPerIterationMs = 0.0f;
    float avgPerEntityUs = 0.0f;  // Microseconds per entity
    float minMs = 0.0f;
    float maxMs = 0.0f;
    size_t memoryUsedBytes = 0;
};

/*
 * Benchmark - ECS performance testing
 */
class Benchmark
{
public:
    /*
     * Run all benchmarks and return results
     */
    static std::vector<BenchmarkResult> RunAll(uint32_t entityCount = 10000,
                                                uint32_t iterations = 100);

    /*
     * Benchmark: Entity creation/destruction
     */
    static BenchmarkResult BenchmarkEntityLifecycle(uint32_t count,
                                                      uint32_t iterations);

    /*
     * Benchmark: Component add/remove
     */
    static BenchmarkResult BenchmarkComponentOperations(uint32_t entityCount,
                                                          uint32_t iterations);

    /*
     * Benchmark: Single component iteration
     */
    static BenchmarkResult BenchmarkSingleComponentIteration(uint32_t entityCount,
                                                               uint32_t iterations);

    /*
     * Benchmark: Multi-component iteration
     */
    static BenchmarkResult BenchmarkMultiComponentIteration(uint32_t entityCount,
                                                              uint32_t iterations);

    /*
     * Benchmark: Position sync from mock data
     */
    static BenchmarkResult BenchmarkPositionSync(uint32_t entityCount,
                                                   uint32_t iterations);

    /*
     * Benchmark: Spatial query (find nearby)
     */
    static BenchmarkResult BenchmarkSpatialQuery(uint32_t entityCount,
                                                   uint32_t queryCount);

    /*
     * Estimate memory usage per entity
     */
    static size_t EstimateMemoryPerEntity();

    /*
     * Print results to log
     */
    static void LogResults(const std::vector<BenchmarkResult>& results);

    /*
     * Compare with OOP baseline (if available)
     */
    static void CompareWithBaseline(const std::vector<BenchmarkResult>& ecsResults);
};

/*
 * ScopedTimer - RAII timer for benchmarking
 */
class ScopedTimer
{
public:
    ScopedTimer(float& outMs);
    ~ScopedTimer();

private:
    float& m_outMs;
    uint32_t m_startTime;
};

} // namespace ecs

#endif // _PLAYERBOT_ECS_BENCHMARK_H
