/*
 * ECS - Entity Component System for Swarm Playerbots
 *
 * Main header file - includes all ECS components.
 *
 * Architecture Overview:
 * - EntityId: Packed 64-bit identifier with type/generation/index
 * - Component: Plain data struct (POD-like)
 * - ComponentArray: Contiguous storage with sparse-set pattern
 * - Registry: Central manager for entities and components
 * - View: Query helper for multi-component iteration
 *
 * Design Goals:
 * - Cache-friendly data layout (components contiguous in memory)
 * - O(1) component access by entity
 * - Fast batch iteration for systems
 * - Incremental migration from existing OOP architecture
 *
 * Usage Example:
 * ```cpp
 * #include "ecs/ECS.h"
 *
 * // Define components
 * struct Position { float x, y, z; uint32_t mapId; };
 * struct Velocity { float dx, dy, dz; };
 *
 * // Create registry and entities
 * ecs::Registry registry;
 * registry.Reserve(10000);  // Pre-allocate for 10k entities
 *
 * EntityId bot = registry.CreateEntity(EntityType::Bot);
 * registry.AddComponent<Position>(bot, {100.0f, 200.0f, 0.0f, 0});
 * registry.AddComponent<Velocity>(bot, {1.0f, 0.0f, 0.0f});
 *
 * // Batch update all entities with both components
 * registry.ForEach<Position>([](EntityId id, Position& pos) {
 *     // Process each position
 * });
 *
 * // Or use View for multi-component queries
 * for (auto [id, pos, vel] : ecs::View<Position, Velocity>(registry)) {
 *     pos.x += vel.dx;
 *     pos.y += vel.dy;
 *     pos.z += vel.dz;
 * }
 * ```
 */

#ifndef _PLAYERBOT_ECS_H
#define _PLAYERBOT_ECS_H

#include "Types.h"
#include "ComponentArray.h"
#include "Registry.h"
#include "Components.h"
#include "BotRegistry.h"
#include "Systems.h"
#include "ValueCache.h"
#include "TriggerHelpers.h"
#include "Benchmark.h"

// Convenience namespace alias
namespace ECS = ecs;

#endif // _PLAYERBOT_ECS_H
