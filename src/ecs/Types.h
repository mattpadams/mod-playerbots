/*
 * ECS Core Types - Swarm Playerbot Architecture
 *
 * Defines fundamental types for the Entity Component System:
 * - EntityId: Strongly-typed entity identifier with generation counter
 * - ComponentTypeId: Type-safe component identification
 * - EntityType: Classification of entities (bot, player, npc, etc.)
 */

#ifndef _PLAYERBOT_ECS_TYPES_H
#define _PLAYERBOT_ECS_TYPES_H

#include <cstdint>
#include <limits>
#include <functional>

namespace ecs {

// Forward declarations
class Registry;

/*
 * EntityId - Packed 64-bit identifier
 *
 * Layout (64 bits):
 *   [63:56] - Type (8 bits): EntityType enum
 *   [55:32] - Generation (24 bits): Reuse counter for slot recycling
 *   [31:0]  - Index (32 bits): Slot index in entity array
 *
 * This design allows:
 * - 4 billion+ unique entity slots
 * - 16 million generations before wrap (detects stale references)
 * - 256 entity types
 * - O(1) validity checking
 */
struct EntityId
{
    uint64_t value;

    // Bit layout constants
    static constexpr uint64_t INDEX_BITS = 32;
    static constexpr uint64_t GENERATION_BITS = 24;
    static constexpr uint64_t TYPE_BITS = 8;

    static constexpr uint64_t INDEX_MASK = (1ULL << INDEX_BITS) - 1;
    static constexpr uint64_t GENERATION_MASK = ((1ULL << GENERATION_BITS) - 1) << INDEX_BITS;
    static constexpr uint64_t TYPE_MASK = ((1ULL << TYPE_BITS) - 1) << (INDEX_BITS + GENERATION_BITS);

    // Invalid entity constant
    static constexpr uint64_t INVALID_VALUE = std::numeric_limits<uint64_t>::max();

    // Constructors
    constexpr EntityId() : value(INVALID_VALUE) {}
    constexpr explicit EntityId(uint64_t v) : value(v) {}
    constexpr EntityId(uint32_t index, uint32_t generation, uint8_t type)
        : value(static_cast<uint64_t>(index) |
                (static_cast<uint64_t>(generation) << INDEX_BITS) |
                (static_cast<uint64_t>(type) << (INDEX_BITS + GENERATION_BITS))) {}

    // Accessors
    [[nodiscard]] constexpr uint32_t Index() const { return static_cast<uint32_t>(value & INDEX_MASK); }
    [[nodiscard]] constexpr uint32_t Generation() const { return static_cast<uint32_t>((value & GENERATION_MASK) >> INDEX_BITS); }
    [[nodiscard]] constexpr uint8_t Type() const { return static_cast<uint8_t>((value & TYPE_MASK) >> (INDEX_BITS + GENERATION_BITS)); }

    // Validity
    [[nodiscard]] constexpr bool IsValid() const { return value != INVALID_VALUE; }
    constexpr explicit operator bool() const { return IsValid(); }

    // Comparison
    constexpr bool operator==(const EntityId& other) const { return value == other.value; }
    constexpr bool operator!=(const EntityId& other) const { return value != other.value; }
    constexpr bool operator<(const EntityId& other) const { return value < other.value; }

    // Static factory for invalid ID
    static constexpr EntityId Invalid() { return EntityId(); }
};

/*
 * EntityType - Classification of entities in the system
 *
 * Used for:
 * - Fast type checking without component lookup
 * - Type-specific processing batches
 * - Debugging and logging
 */
enum class EntityType : uint8_t
{
    Invalid     = 0,
    Bot         = 1,    // AI-controlled player bot
    RealPlayer  = 2,    // Human-controlled player (reference only)
    NPC         = 3,    // Non-player character (reference only)
    Squad       = 4,    // Squad leader entity (hierarchical AI)
    Zone        = 5,    // Zone management entity
    Reserved1   = 6,
    Reserved2   = 7,
    Max         = 255
};

/*
 * ComponentTypeId - Type identifier for components
 *
 * Generated at compile time using type hashing.
 * Allows runtime component lookup by type.
 */
using ComponentTypeId = uint32_t;

// Compile-time type ID generation
namespace detail {
    // FNV-1a hash for type name string
    constexpr uint32_t FnvHash(const char* str, uint32_t hash = 2166136261u)
    {
        return (*str == 0) ? hash : FnvHash(str + 1, (hash ^ static_cast<uint32_t>(*str)) * 16777619u);
    }
}

// Get unique ID for a component type
template<typename T>
struct ComponentType
{
    static ComponentTypeId Id()
    {
        // Use typeid name hash - each type gets unique ID
        static const ComponentTypeId id = detail::FnvHash(typeid(T).name());
        return id;
    }
};

/*
 * Component trait - ensures components are POD-like
 * Components should be simple data structs for cache efficiency
 */
template<typename T>
struct IsValidComponent
{
    static constexpr bool value = std::is_default_constructible_v<T> &&
                                   std::is_trivially_copyable_v<T>;
};

} // namespace ecs

// Hash support for EntityId in standard containers
namespace std {
    template<>
    struct hash<ecs::EntityId>
    {
        size_t operator()(const ecs::EntityId& id) const noexcept
        {
            return std::hash<uint64_t>{}(id.value);
        }
    };
}

#endif // _PLAYERBOT_ECS_TYPES_H
