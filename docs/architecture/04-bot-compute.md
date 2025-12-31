# Bot Compute Architecture

This document describes the AI processing architecture for bots, including the separation of AI from world simulation and the hierarchical decision-making system.

## Overview

Bot AI processing is deliberately separated from world simulation:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Separation of Concerns                                    │
│                                                                              │
│  ┌─────────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │        Zone Nodes               │  │      Bot Compute Nodes          │  │
│  │   (World Simulation)            │  │     (AI Processing)             │  │
│  │                                 │  │                                 │  │
│  │  Responsibilities:              │  │  Responsibilities:              │  │
│  │  - Entity state authority       │  │  - AI decision making           │  │
│  │  - Combat resolution            │  │  - Pathfinding                  │  │
│  │  - Spell effects                │  │  - Behavior trees               │  │
│  │  - Physics/collision            │  │  - Threat analysis              │  │
│  │  - State persistence            │  │  - Target selection             │  │
│  │                                 │  │  - Squad coordination           │  │
│  │  Scaling factor:                │  │                                 │  │
│  │  Entities in world              │  │  Scaling factor:                │  │
│  │                                 │  │  Bot count                      │  │
│  └─────────────────────────────────┘  └─────────────────────────────────┘  │
│                                                                              │
│  Benefits:                                                                   │
│  - Independent scaling (add AI nodes without touching world sim)            │
│  - Bot AI can be updated/restarted without affecting world state           │
│  - AI crashes don't corrupt world state                                     │
│  - Different update rates (AI at 5Hz, world at 20Hz)                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Bot Compute Node Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Bot Compute Node                                      │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         World View Cache                               │  │
│  │                                                                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │ Cell Cache  │  │ Entity      │  │ Threat      │  │ Path        │   │  │
│  │  │ Subscribed  │  │ Positions   │  │ Tables      │  │ Cache       │   │  │
│  │  │ cells state │  │ (nearby)    │  │ (combat)    │  │ (routes)    │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  │                                                                         │  │
│  │  Updated via pub/sub from Zone Nodes (~50ms latency)                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                        │                                     │
│                                        ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        AI Processing Pipeline                          │  │
│  │                                                                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │  Behavior   │─►│  Decision   │─►│   Action    │─►│  Command    │   │  │
│  │  │  Trees      │  │   Engine    │  │  Validator  │  │  Dispatcher │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  │                                                                         │  │
│  │  Per-bot processing: ~50 microseconds                                  │  │
│  │  Throughput: ~1M decisions/second per node                             │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                        │                                     │
│                                        ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Bot Management                                   │  │
│  │                                                                         │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │ Bot         │  │ Squad       │  │ Load        │  │ Health      │   │  │
│  │  │ Registry    │  │ Manager     │  │ Balancer    │  │ Monitor     │   │  │
│  │  │ (assigned)  │  │ (groups)    │  │ (work dist) │  │ (metrics)   │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  │                                                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Capacity: 50,000 - 100,000 bots per node                                   │
│  CPU: 32-64 cores recommended                                               │
│  Memory: 16-32 GB (for world view cache + AI state)                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## World View Cache

Each Bot Compute Node maintains a local cache of world state:

### Cache Structure

```cpp
class WorldViewCache {
public:
    // Subscribed cells and their state
    std::unordered_map<CellId, CellSnapshot> cells;

    // Nearby entities (within interaction range)
    struct NearbyEntity {
        EntityId id;
        Position position;
        uint32_t health;
        uint32_t max_health;
        uint32_t faction;
        uint8_t  entity_type;
        uint8_t  flags;  // in_combat, pvp, etc.
    };
    SpatialHash<NearbyEntity> entities;

    // Path cache (reusable paths)
    LRUCache<PathKey, Path> path_cache;

    // Threat snapshots (for combat bots)
    std::unordered_map<EntityId, ThreatSnapshot> threat_tables;

    // Update from zone node messages
    void apply_update(const StateUpdate& update);

    // Query methods
    std::vector<NearbyEntity> get_entities_in_range(Position pos, float range);
    std::optional<NearbyEntity> get_entity(EntityId id);
    std::optional<Path> get_cached_path(Position from, Position to);
};
```

### Cache Subscription

```cpp
// Bot Compute Node subscribes to cells containing its bots
void BotComputeNode::manage_subscriptions() {
    std::set<CellId> needed_cells;

    // Collect cells where our bots are located
    for (auto& [id, bot] : assigned_bots) {
        needed_cells.insert(bot.position.cell);

        // Also subscribe to adjacent cells for visibility
        for (CellId neighbor : get_adjacent_cells(bot.position.cell)) {
            needed_cells.insert(neighbor);
        }
    }

    // Subscribe to new cells
    for (CellId cell : needed_cells) {
        if (!subscribed_cells.contains(cell)) {
            message_bus.subscribe(cell_update_topic(cell), this);
            subscribed_cells.insert(cell);
        }
    }

    // Unsubscribe from cells we no longer need
    for (CellId cell : subscribed_cells) {
        if (!needed_cells.contains(cell)) {
            message_bus.unsubscribe(cell_update_topic(cell), this);
            subscribed_cells.erase(cell);
        }
    }
}
```

## Behavior System

### Behavior Tree Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Bot Behavior Tree                                    │
│                                                                              │
│                              ┌─────────┐                                    │
│                              │  Root   │                                    │
│                              │Selector │                                    │
│                              └────┬────┘                                    │
│                                   │                                          │
│         ┌─────────────────────────┼─────────────────────────┐               │
│         │                         │                         │               │
│    ┌────▼────┐              ┌────▼────┐              ┌────▼────┐           │
│    │ Combat  │              │ Follow  │              │  Idle   │           │
│    │Sequence │              │Sequence │              │Sequence │           │
│    └────┬────┘              └────┬────┘              └────┬────┘           │
│         │                        │                        │                 │
│    ┌────┴────────────┐     ┌────┴────┐              ┌────┴────┐           │
│    │                 │     │         │              │         │           │
│ ┌──▼──┐  ┌──▼──┐ ┌──▼──┐ ┌▼────┐  ┌▼────┐       ┌▼────┐  ┌▼────┐       │
│ │Check│  │Select│ │Use  │ │Move │  │Check│       │Rest │  │Look │       │
│ │Enemy│  │Target│ │Abil │ │To   │  │Dist │       │    │  │Around│       │
│ │Near │  │     │ │ity  │ │Lead │  │     │       │    │  │     │       │
│ └─────┘  └─────┘ └─────┘ └─────┘  └─────┘       └─────┘  └─────┘       │
│                                                                              │
│  Priority: Combat > Follow > Idle                                           │
│  Each node returns: SUCCESS, FAILURE, or RUNNING                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Behavior Node Implementation

```cpp
enum class BehaviorStatus {
    SUCCESS,
    FAILURE,
    RUNNING
};

class BehaviorNode {
public:
    virtual ~BehaviorNode() = default;
    virtual BehaviorStatus tick(BotContext& ctx) = 0;
};

// Selector: tries children until one succeeds
class Selector : public BehaviorNode {
    std::vector<std::unique_ptr<BehaviorNode>> children;

public:
    BehaviorStatus tick(BotContext& ctx) override {
        for (auto& child : children) {
            auto status = child->tick(ctx);
            if (status != BehaviorStatus::FAILURE) {
                return status;
            }
        }
        return BehaviorStatus::FAILURE;
    }
};

// Sequence: executes children until one fails
class Sequence : public BehaviorNode {
    std::vector<std::unique_ptr<BehaviorNode>> children;
    size_t current_child = 0;

public:
    BehaviorStatus tick(BotContext& ctx) override {
        while (current_child < children.size()) {
            auto status = children[current_child]->tick(ctx);
            if (status == BehaviorStatus::RUNNING) {
                return BehaviorStatus::RUNNING;
            }
            if (status == BehaviorStatus::FAILURE) {
                current_child = 0;
                return BehaviorStatus::FAILURE;
            }
            current_child++;
        }
        current_child = 0;
        return BehaviorStatus::SUCCESS;
    }
};

// Example leaf node: Check if enemies nearby
class CheckEnemyNear : public BehaviorNode {
public:
    BehaviorStatus tick(BotContext& ctx) override {
        auto enemies = ctx.world_view.get_hostile_entities_in_range(
            ctx.bot.position, 40.0f);

        if (!enemies.empty()) {
            ctx.blackboard.set("nearby_enemies", enemies);
            return BehaviorStatus::SUCCESS;
        }
        return BehaviorStatus::FAILURE;
    }
};
```

## Hierarchical AI (Squad System)

Instead of each bot running full AI, we use hierarchical decision-making:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Hierarchical AI System                                 │
│                                                                              │
│  Traditional (500 bots = 500 full AI evaluations):                          │
│                                                                              │
│  Bot 1: [Sense] → [Think] → [Act]                                           │
│  Bot 2: [Sense] → [Think] → [Act]                                           │
│  Bot 3: [Sense] → [Think] → [Act]                                           │
│  ...                                                                         │
│  Bot 500: [Sense] → [Think] → [Act]                                         │
│                                                                              │
│  Cost: 500 × full behavior tree evaluation                                  │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Hierarchical (500 bots = 100 squad leaders + 400 simple followers):        │
│                                                                              │
│  Squad 1 Leader: [Full AI] → Commands → [Tank: "Engage X"]                  │
│                                        → [Healer: "Heal Tank"]               │
│                                        → [DPS 1-3: "Attack X"]               │
│                                                                              │
│  Squad 2 Leader: [Full AI] → Commands → [Members...]                        │
│  ...                                                                         │
│                                                                              │
│  Cost: 100 × full AI + 400 × simple command execution                       │
│  Savings: ~80% reduction in AI computation                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Squad Structure

```cpp
struct Squad {
    EntityId leader;
    std::vector<EntityId> members;

    // Formation
    FormationType formation;  // LINE, CIRCLE, WEDGE, etc.
    float spread;             // Distance between members

    // Current objective
    SquadObjective objective;  // FOLLOW_PLAYER, ATTACK_TARGET, PATROL, etc.
    EntityId objective_target;

    // State
    SquadState state;  // IDLE, MOVING, COMBAT, REGROUPING
};

struct SquadCommand {
    CommandType type;
    EntityId target;       // For ATTACK, HEAL, FOLLOW
    Position destination;  // For MOVE, POSITION
    uint8_t priority;      // 0-255, higher = more urgent
    uint32_t issued_at;    // Tick number
};

enum class CommandType {
    ATTACK,           // Engage this target
    HEAL,             // Heal this target
    FOLLOW,           // Follow this entity
    MOVE_TO,          // Move to position
    HOLD_POSITION,    // Stay here
    USE_ABILITY,      // Use specific ability
    RETREAT,          // Fall back
    ASSIST,           // Help squad leader's target
};
```

### Squad Leader AI

```cpp
class SquadLeaderAI {
public:
    void update(Squad& squad, WorldViewCache& world) {
        // 1. Assess situation
        auto threats = assess_threats(squad, world);
        auto resources = assess_resources(squad);

        // 2. Determine objective
        auto objective = determine_objective(squad, threats, resources);

        // 3. Assign roles
        assign_combat_roles(squad, objective);

        // 4. Issue commands to members
        for (EntityId member : squad.members) {
            auto role = get_member_role(member);
            auto command = generate_command(role, objective, world);
            dispatch_command(member, command);
        }
    }

private:
    void assign_combat_roles(Squad& squad, const Objective& obj) {
        // Tank: highest armor/health, engage primary target
        // Healer: healing class, keep tank alive
        // DPS: damage dealers, assist on marked targets

        std::sort(squad.members.begin(), squad.members.end(),
            [](EntityId a, EntityId b) {
                return get_tank_score(a) > get_tank_score(b);
            });

        EntityId tank = squad.members[0];
        roles[tank] = Role::TANK;

        for (EntityId m : squad.members) {
            if (is_healer_class(m)) {
                roles[m] = Role::HEALER;
            } else if (m != tank) {
                roles[m] = Role::DPS;
            }
        }
    }
};
```

### Squad Member AI (Simplified)

```cpp
class SquadMemberAI {
public:
    BehaviorStatus update(Bot& bot, const SquadCommand& command) {
        // Members execute simple commands without complex decision-making

        switch (command.type) {
            case CommandType::ATTACK:
                return execute_attack(bot, command.target);

            case CommandType::HEAL:
                return execute_heal(bot, command.target);

            case CommandType::FOLLOW:
                return execute_follow(bot, command.target);

            case CommandType::MOVE_TO:
                return execute_move(bot, command.destination);

            case CommandType::HOLD_POSITION:
                return BehaviorStatus::SUCCESS;

            case CommandType::RETREAT:
                return execute_retreat(bot);

            default:
                return BehaviorStatus::FAILURE;
        }
    }

private:
    BehaviorStatus execute_attack(Bot& bot, EntityId target) {
        // Simple attack loop - no target selection needed
        if (!is_in_range(bot, target)) {
            move_towards(bot, target);
            return BehaviorStatus::RUNNING;
        }

        auto ability = select_best_ability(bot, target);
        if (ability) {
            queue_action(bot, UseAbility{ability, target});
        }
        return BehaviorStatus::RUNNING;
    }
};
```

## AI Update Loop

```cpp
class BotComputeNode {
public:
    void ai_update_loop() {
        const auto tick_duration = std::chrono::milliseconds(200);  // 5 Hz

        while (running) {
            auto tick_start = std::chrono::steady_clock::now();

            // 1. Process incoming world state updates
            process_world_updates();

            // 2. Update squad leaders (full AI)
            for (auto& squad : squads) {
                squad_leader_ai.update(squad, world_cache);
            }

            // 3. Update individual bots (in parallel)
            parallel_for(assigned_bots, [&](Bot& bot) {
                if (bot.is_squad_leader) {
                    // Already updated above
                    return;
                }

                if (bot.squad_id != INVALID_SQUAD) {
                    // Squad member - execute command
                    auto command = get_pending_command(bot.id);
                    member_ai.update(bot, command);
                } else {
                    // Solo bot - full AI
                    solo_ai.update(bot, world_cache);
                }
            });

            // 4. Dispatch actions to Zone Nodes
            dispatch_pending_actions();

            // 5. Wait for next tick
            auto elapsed = std::chrono::steady_clock::now() - tick_start;
            if (elapsed < tick_duration) {
                std::this_thread::sleep_for(tick_duration - elapsed);
            }
        }
    }
};
```

## Action Dispatch

When AI decides on actions, they're sent to Zone Nodes for validation:

```cpp
struct BotAction {
    EntityId bot_id;
    ActionType type;
    EntityId target;
    uint32_t ability_id;
    Position destination;
    uint64_t tick_number;
};

class ActionDispatcher {
public:
    void dispatch(const std::vector<BotAction>& actions) {
        // Group actions by destination Zone Node
        std::map<NodeId, std::vector<BotAction>> grouped;

        for (const auto& action : actions) {
            CellId cell = get_bot_cell(action.bot_id);
            NodeId zone_node = get_cell_owner(cell);
            grouped[zone_node].push_back(action);
        }

        // Send batched actions to each Zone Node
        for (auto& [node, batch] : grouped) {
            ActionBatch msg{
                .source_node = this_node_id,
                .tick = current_tick,
                .actions = std::move(batch)
            };
            message_bus.send(node, msg);
        }
    }
};
```

## Pathfinding

### Hierarchical Pathfinding

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Hierarchical Pathfinding                                  │
│                                                                              │
│  Level 0: Continent Graph (coarse)                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌───────┐     ┌───────┐     ┌───────┐     ┌───────┐               │   │
│  │  │Elwynn │────►│Westfall│────►│Duskwood│────►│Stranglethorn│        │   │
│  │  └───────┘     └───────┘     └───────┘     └───────┘               │   │
│  │                                                                       │   │
│  │  Precomputed connections between zones                               │   │
│  │  ~100 nodes per continent                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Level 1: Zone Graph (medium)                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ┌───┐  ┌───┐  ┌───┐  ┌───┐  ┌───┐                                 │   │
│  │  │ A │──│ B │──│ C │──│ D │──│ E │  (Elwynn Forest internal)       │   │
│  │  └───┘  └───┘  └───┘  └───┘  └───┘                                 │   │
│  │                                                                       │   │
│  │  ~500 nodes per zone                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Level 2: Detail Navmesh (fine)                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Standard navmesh for local pathfinding                              │   │
│  │  Only loaded for areas with active bots                             │   │
│  │  ~10,000 triangles per cell                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Path Caching

```cpp
struct PathKey {
    CellId from_cell;
    CellId to_cell;
    // Quantized positions (1 yard resolution)
    int16_t from_x, from_y;
    int16_t to_x, to_y;

    bool operator==(const PathKey& other) const = default;
    size_t hash() const { /* combine fields */ }
};

class PathCache {
    LRUCache<PathKey, Path> cache;
    std::shared_mutex mutex;

public:
    std::optional<Path> get(Position from, Position to) {
        PathKey key = make_key(from, to);

        std::shared_lock lock(mutex);
        return cache.get(key);
    }

    void put(Position from, Position to, Path path) {
        PathKey key = make_key(from, to);

        std::unique_lock lock(mutex);
        cache.put(key, std::move(path));
    }

    // Invalidate when world changes (e.g., door opens/closes)
    void invalidate_cell(CellId cell) {
        std::unique_lock lock(mutex);
        cache.remove_if([&](const PathKey& k) {
            return k.from_cell == cell || k.to_cell == cell;
        });
    }
};
```

## Performance Metrics

### Per-Bot Processing Time Budget

| Operation | Budget | Actual (avg) |
|-----------|--------|--------------|
| World view query | 5 μs | 2 μs |
| Behavior tree tick | 30 μs | 15 μs |
| Pathfinding (cached) | 5 μs | 1 μs |
| Pathfinding (compute) | 100 μs | 80 μs |
| Action validation | 5 μs | 3 μs |
| **Total (simple)** | **45 μs** | **21 μs** |
| **Total (with path)** | **145 μs** | **100 μs** |

### Node Capacity

```
32-core server, 5 Hz update rate:
- Available compute time per tick: 32 cores × 200ms = 6,400 core-ms
- Per-bot average (with 10% pathfinding): 25 μs = 0.025 ms
- Theoretical max: 6,400 / 0.025 = 256,000 bots
- Practical max (with overhead): ~100,000 bots per node
```

## Configuration

```yaml
# bot-compute-node.yaml
ai:
  tick_rate_hz: 5
  behavior_tree_timeout_ms: 10
  max_decisions_per_tick: 200000

squad:
  enabled: true
  max_size: 5
  leader_full_ai: true
  member_simplified_ai: true
  formation_update_rate_hz: 1

pathfinding:
  cache_size: 100000
  cache_ttl_seconds: 300
  max_path_length: 1000
  hierarchical_enabled: true

world_cache:
  max_cells: 500
  entity_range: 100  # yards
  update_buffer_size: 10000
```

## Next Steps

- [05-communication.md](05-communication.md) - How bots receive world updates
- [06-consistency.md](06-consistency.md) - Handling stale world view
