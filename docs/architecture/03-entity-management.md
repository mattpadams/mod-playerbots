# Entity Management

This document describes the entity lifecycle, state representation, and migration protocols.

## Entity Model

### Entity Component System (ECS)

Unlike the traditional OOP approach (`Player` inherits `Unit` inherits `Object`), Swarm uses an Entity Component System:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Entity Component System                               │
│                                                                              │
│  Traditional OOP:                    ECS Approach:                          │
│                                                                              │
│  ┌─────────────┐                    Entity = just an ID (uint64)            │
│  │   Object    │                                                             │
│  └──────┬──────┘                    Components = pure data structs:         │
│         │                            ┌────────────────────────────────────┐ │
│  ┌──────▼──────┐                    │ Position { x, y, z, orientation }  │ │
│  │    Unit     │                    │ Health { current, max }            │ │
│  └──────┬──────┘                    │ Combat { target, threat_list }     │ │
│         │                            │ Movement { speed, path }           │ │
│  ┌──────▼──────┐                    │ AI { state, behavior_tree }        │ │
│  │   Player    │                    │ Inventory { items[], gold }        │ │
│  └─────────────┘                    │ ...                                │ │
│                                      └────────────────────────────────────┘ │
│  Problems:                                                                   │
│  - Deep inheritance hierarchy        Systems = stateless processors:        │
│  - Virtual function overhead         ┌────────────────────────────────────┐ │
│  - Poor cache locality               │ MovementSystem::update(positions)  │ │
│  - Hard to parallelize               │ CombatSystem::update(combat, pos)  │ │
│                                      │ AISystem::update(ai, world_view)   │ │
│                                      └────────────────────────────────────┘ │
│                                                                              │
│                                      Benefits:                               │
│                                      - Cache-friendly iteration             │
│                                      - Easy parallelization                 │
│                                      - Bots skip irrelevant components      │
│                                      - Hot/cold data separation             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Entity ID Structure

```cpp
// 64-bit globally unique entity identifier
struct EntityId {
    uint64_t value;

    // Bit layout:
    // [63:56] - Entity type (8 bits: player, npc, bot, gameobject, etc.)
    // [55:48] - Origin node (8 bits: for debugging/routing)
    // [47:0]  - Sequence number (48 bits: ~281 trillion unique IDs)

    EntityType type() const { return EntityType((value >> 56) & 0xFF); }
    NodeId origin_node() const { return NodeId((value >> 48) & 0xFF); }
    uint64_t sequence() const { return value & 0xFFFFFFFFFFFF; }

    static EntityId generate(EntityType type, NodeId node) {
        static std::atomic<uint64_t> counter{0};
        return EntityId{
            (uint64_t(type) << 56) |
            (uint64_t(node) << 48) |
            (counter.fetch_add(1) & 0xFFFFFFFFFFFF)
        };
    }
};

enum class EntityType : uint8_t {
    PLAYER      = 0,
    BOT         = 1,
    NPC         = 2,
    CREATURE    = 3,
    GAMEOBJECT  = 4,
    CORPSE      = 5,
    PROJECTILE  = 6,
    AREA_EFFECT = 7,
    // ...
};
```

## Component Definitions

### Core Components (All Entities)

```cpp
// Position in world space
struct PositionComponent {
    CellId   cell;          // Current cell
    float    x, y, z;       // World coordinates
    float    orientation;   // Facing direction (radians)
    uint64_t timestamp;     // Last update time
};  // 32 bytes

// Health and resources
struct VitalsComponent {
    uint32_t health;
    uint32_t max_health;
    uint32_t power;         // Mana, rage, energy, etc.
    uint32_t max_power;
    uint8_t  power_type;
    uint8_t  alive;         // 0 = dead, 1 = alive
    uint16_t padding;
};  // 20 bytes

// Faction and targeting
struct FactionComponent {
    uint32_t faction_id;
    uint32_t faction_template;
    uint8_t  pvp_flags;
    uint8_t  padding[3];
};  // 12 bytes
```

### Combat Components

```cpp
// Active combat state
struct CombatComponent {
    EntityId target;
    uint64_t combat_start_time;
    uint8_t  in_combat;
    uint8_t  attack_state;
    uint16_t swing_timer;

    // Threat table (separate allocation for creatures)
    ThreatList* threat_list;  // nullptr for players/bots
};  // 24 bytes

// Active buffs/debuffs
struct AuraComponent {
    static const int MAX_AURAS = 64;

    struct Aura {
        uint32_t spell_id;
        EntityId caster;
        uint32_t duration_remaining;
        uint8_t  stacks;
        uint8_t  flags;
    };

    Aura auras[MAX_AURAS];
    uint8_t aura_count;
};  // ~1KB

// Spell casting
struct SpellComponent {
    uint32_t casting_spell_id;
    EntityId spell_target;
    uint32_t cast_time_remaining;
    uint32_t gcd_remaining;

    // Cooldowns stored separately in cooldown system
};  // 20 bytes
```

### Bot-Specific Components

```cpp
// AI decision-making state
struct AIComponent {
    uint8_t  behavior_state;    // IDLE, FOLLOWING, COMBAT, GATHERING, etc.
    uint8_t  role;              // TANK, HEALER, DPS, SUPPORT
    uint16_t action_timer;      // Ticks until next decision

    EntityId follow_target;     // Who to follow
    EntityId assist_target;     // Who to assist in combat

    // Hierarchical AI (for squad members)
    EntityId squad_leader;      // nullptr if solo or leader
    uint32_t last_command;      // Command from leader

    // Behavior tree node pointer (managed separately)
    void*    behavior_tree;
};  // 40 bytes

// Bot configuration
struct BotConfigComponent {
    uint32_t template_id;       // Character template
    uint8_t  class_id;
    uint8_t  race_id;
    uint8_t  level;
    uint8_t  spec;

    // Behavior settings
    uint8_t  aggression;        // 0-100
    uint8_t  follow_distance;   // yards
    uint8_t  assist_priority;   // 0 = leader, 1 = marks, 2 = nearest
    uint8_t  flags;             // auto-loot, auto-roll, etc.
};  // 12 bytes
```

### Heavy Components (Separate Storage)

```cpp
// Inventory - stored in separate table, loaded on demand
struct InventoryComponent {
    static const int MAX_SLOTS = 150;

    struct ItemSlot {
        uint32_t item_id;
        uint32_t stack_count;
        uint32_t enchant_id;
        uint8_t  slot;
        uint8_t  bag;
        uint8_t  flags;
        uint8_t  durability;
    };

    ItemSlot items[MAX_SLOTS];
    uint64_t gold;
};  // ~2.5KB - NOT stored inline

// Quest state - stored separately
struct QuestComponent {
    static const int MAX_QUESTS = 25;

    struct QuestProgress {
        uint32_t quest_id;
        uint8_t  status;
        uint8_t  objectives[4];
    };

    QuestProgress quests[MAX_QUESTS];
};  // ~250 bytes - loaded on demand
```

## Entity State Summary

### Bot Entity (Optimized for Network)

```cpp
// Core bot state for network replication: ~200 bytes
struct BotCoreState {
    EntityId          id;           // 8 bytes
    PositionComponent position;     // 32 bytes
    VitalsComponent   vitals;       // 20 bytes
    FactionComponent  faction;      // 12 bytes
    CombatComponent   combat;       // 24 bytes
    SpellComponent    spell;        // 20 bytes
    AIComponent       ai;           // 40 bytes
    BotConfigComponent config;      // 12 bytes

    uint64_t version;               // 8 bytes - for sync
    uint64_t last_update;           // 8 bytes
};

// Total core state: ~200 bytes per bot
// For 1 million bots: ~200 MB (easily fits in memory)

// Heavy state loaded on demand:
// - Inventory: ~2.5KB
// - Auras: ~1KB
// - Quest progress: ~250 bytes
// - Spell cooldowns: ~500 bytes
```

## Entity Registry

The Entity Registry is a distributed hash table (DHT) for locating entities:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Entity Registry (DHT)                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Consistent Hash Ring                            │   │
│  │                                                                       │   │
│  │                           Node 1                                      │   │
│  │                          ┌─────┐                                      │   │
│  │                       ┌──┤     ├──┐                                   │   │
│  │                      │  └─────┘  │                                   │   │
│  │               Node 4 │           │ Node 2                            │   │
│  │              ┌─────┐ │           │ ┌─────┐                           │   │
│  │              │     ├─┘           └─┤     │                           │   │
│  │              └──┬──┘               └──┬──┘                           │   │
│  │                 │                     │                               │   │
│  │                 └────────┬────────────┘                               │   │
│  │                       ┌──┴──┐                                         │   │
│  │                       │     │ Node 3                                  │   │
│  │                       └─────┘                                         │   │
│  │                                                                       │   │
│  │  Entity ID hashes to position on ring                                │   │
│  │  Responsible node = next node clockwise                              │   │
│  │  Replication factor = 3 (stored on 3 consecutive nodes)              │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Registry Entry:                                                            │
│  {                                                                          │
│      "entity_id": 0x0100000000012345,                                       │
│      "owner_cell": { "continent": 0, "x": 24, "y": 32, "level": 0 },       │
│      "owner_node": "zone-node-7",                                           │
│      "last_seen": 1703548800000,                                            │
│      "version": 42                                                          │
│  }                                                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Registry Operations

```cpp
class EntityRegistry {
public:
    // Locate an entity
    EntityLocation locate(EntityId id) {
        NodeId responsible = hash_ring.get_node(id);
        return rpc_call(responsible, "lookup", id);
    }

    // Update entity location (called on cell transitions)
    void update_location(EntityId id, CellId new_cell, NodeId new_node) {
        NodeId responsible = hash_ring.get_node(id);
        rpc_call(responsible, "update", id, new_cell, new_node);

        // Gossip to replicas
        for (NodeId replica : hash_ring.get_replicas(id, 3)) {
            async_rpc(replica, "replicate", id, new_cell, new_node);
        }
    }

    // Batch lookup for efficiency
    std::vector<EntityLocation> locate_batch(std::vector<EntityId>& ids) {
        // Group by responsible node
        std::map<NodeId, std::vector<EntityId>> groups;
        for (EntityId id : ids) {
            groups[hash_ring.get_node(id)].push_back(id);
        }

        // Parallel lookups
        std::vector<std::future<std::vector<EntityLocation>>> futures;
        for (auto& [node, node_ids] : groups) {
            futures.push_back(async_rpc(node, "batch_lookup", node_ids));
        }

        // Collect results
        std::vector<EntityLocation> results;
        for (auto& f : futures) {
            auto batch = f.get();
            results.insert(results.end(), batch.begin(), batch.end());
        }
        return results;
    }
};
```

## Entity Migration

When an entity moves between cells owned by different nodes:

### Migration Sequence

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Entity Migration Protocol                              │
│                                                                              │
│   Source Node           Coordinator           Destination Node              │
│       (A)                   (C)                     (B)                     │
│        │                     │                       │                       │
│        │                     │                       │                       │
│   ┌────┴────┐                │                       │                       │
│   │ Entity  │                │                       │                       │
│   │ crosses │                │                       │                       │
│   │boundary │                │                       │                       │
│   └────┬────┘                │                       │                       │
│        │                     │                       │                       │
│        │  1. MigrationStart  │                       │                       │
│        │────────────────────►│                       │                       │
│        │                     │                       │                       │
│        │                     │  2. PrepareReceive    │                       │
│        │                     │──────────────────────►│                       │
│        │                     │                       │                       │
│        │                     │                ┌──────┴──────┐                │
│        │                     │                │  Allocate   │                │
│        │                     │                │  resources  │                │
│        │                     │                └──────┬──────┘                │
│        │                     │                       │                       │
│        │                     │  3. ReadyToReceive    │                       │
│        │                     │◄──────────────────────│                       │
│        │                     │                       │                       │
│        │  4. TransferApproved│                       │                       │
│        │◄────────────────────│                       │                       │
│        │                     │                       │                       │
│   ┌────┴────┐                │                       │                       │
│   │ Freeze  │                │                       │                       │
│   │ entity  │                │                       │                       │
│   │ actions │                │                       │                       │
│   └────┬────┘                │                       │                       │
│        │                     │                       │                       │
│        │         5. EntityState (direct transfer)    │                       │
│        │────────────────────────────────────────────►│                       │
│        │                     │                       │                       │
│        │                     │                ┌──────┴──────┐                │
│        │                     │                │  Validate   │                │
│        │                     │                │  & activate │                │
│        │                     │                └──────┬──────┘                │
│        │                     │                       │                       │
│        │         6. TransferComplete                 │                       │
│        │◄────────────────────────────────────────────│                       │
│        │                     │                       │                       │
│   ┌────┴────┐                │                       │                       │
│   │ Remove  │                │                       │                       │
│   │ local   │                │                       │                       │
│   │ state   │                │                       │                       │
│   └────┬────┘                │                       │                       │
│        │                     │                       │                       │
│        │  7. MigrationComplete                       │                       │
│        │────────────────────►│                       │                       │
│        │                     │                       │                       │
│        │                     │  8. UpdateRegistry    │                       │
│        │                     │──────────────────────►│ (broadcast)           │
│        │                     │                       │                       │
│                                                                              │
│   Total time: ~20-50ms                                                      │
│   Entity frozen: steps 5-6 (~5-10ms)                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Migration State Machine

```cpp
enum class MigrationState {
    NONE,
    INITIATED,      // Source requested migration
    PREPARING,      // Destination preparing resources
    TRANSFERRING,   // State being transferred
    ACTIVATING,     // Destination activating entity
    COMPLETING,     // Cleaning up source
    COMPLETE
};

struct MigrationContext {
    EntityId entity_id;
    CellId source_cell;
    CellId dest_cell;
    NodeId source_node;
    NodeId dest_node;
    MigrationState state;
    uint64_t started_at;
    uint64_t timeout;

    // Entity state snapshot
    std::vector<uint8_t> serialized_state;
};
```

### Failure Handling During Migration

```cpp
void handle_migration_failure(MigrationContext& ctx, FailureReason reason) {
    switch (ctx.state) {
        case MigrationState::INITIATED:
        case MigrationState::PREPARING:
            // Destination not ready - abort, entity stays at source
            ctx.source_node.unfreeze_entity(ctx.entity_id);
            break;

        case MigrationState::TRANSFERRING:
            // Transfer failed - entity may be in limbo
            // Recovery: check both nodes, single source of truth is event log
            if (ctx.dest_node.has_entity(ctx.entity_id)) {
                // Destination has it - complete migration
                ctx.source_node.remove_entity(ctx.entity_id);
            } else {
                // Source still has it - abort
                ctx.source_node.unfreeze_entity(ctx.entity_id);
            }
            break;

        case MigrationState::ACTIVATING:
            // Destination has entity but failed to activate
            // Retry activation or escalate
            retry_activation(ctx);
            break;
    }

    // Log for debugging
    log_migration_failure(ctx, reason);
}
```

## State Serialization

### Binary Format

```cpp
// Efficient binary serialization for network transfer
struct EntityStateBuffer {
    uint8_t* data;
    size_t   size;
    size_t   capacity;

    // Write component with type tag
    template<typename T>
    void write_component(ComponentType type, const T& component) {
        write<uint8_t>(static_cast<uint8_t>(type));
        write<uint16_t>(sizeof(T));
        write_bytes(&component, sizeof(T));
    }

    // Read component
    template<typename T>
    bool read_component(ComponentType expected, T& component) {
        auto type = read<uint8_t>();
        auto size = read<uint16_t>();
        if (type != static_cast<uint8_t>(expected) || size != sizeof(T)) {
            skip(size);
            return false;
        }
        read_bytes(&component, sizeof(T));
        return true;
    }
};

// Serialize bot for migration
EntityStateBuffer serialize_bot(EntityId id, BotCoreState& state) {
    EntityStateBuffer buf;
    buf.reserve(512);

    // Header
    buf.write<uint64_t>(id.value);
    buf.write<uint64_t>(state.version);

    // Components
    buf.write_component(ComponentType::POSITION, state.position);
    buf.write_component(ComponentType::VITALS, state.vitals);
    buf.write_component(ComponentType::FACTION, state.faction);
    buf.write_component(ComponentType::COMBAT, state.combat);
    buf.write_component(ComponentType::SPELL, state.spell);
    buf.write_component(ComponentType::AI, state.ai);
    buf.write_component(ComponentType::CONFIG, state.config);

    return buf;
}
```

## State Versioning

### Vector Clocks for Consistency

```cpp
struct VectorClock {
    std::map<NodeId, uint64_t> clock;

    void increment(NodeId node) {
        clock[node]++;
    }

    void merge(const VectorClock& other) {
        for (auto& [node, time] : other.clock) {
            clock[node] = std::max(clock[node], time);
        }
    }

    bool happened_before(const VectorClock& other) const {
        bool dominated = false;
        for (auto& [node, time] : other.clock) {
            auto it = clock.find(node);
            uint64_t my_time = (it != clock.end()) ? it->second : 0;
            if (my_time > time) return false;
            if (my_time < time) dominated = true;
        }
        return dominated;
    }
};

// Each entity state update includes version
struct StateUpdate {
    EntityId entity_id;
    VectorClock version;
    ComponentType component;
    std::vector<uint8_t> data;
};
```

## Next Steps

- [04-bot-compute.md](04-bot-compute.md) - AI processing architecture
- [05-communication.md](05-communication.md) - How updates are communicated
