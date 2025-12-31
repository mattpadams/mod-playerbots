# Spatial Sharding

This document describes how the game world is partitioned across Zone Nodes for distributed processing.

## Overview

The game world is divided into **spatial cells** - rectangular regions that are assigned to Zone Nodes. This approach:

- Enables horizontal scaling (more nodes = more capacity)
- Localizes entity interactions (most interactions are with nearby entities)
- Allows dynamic load balancing (hot spots can be split)
- Minimizes cross-node communication

## Cell Structure

### Basic Cell Definition

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Continent: Eastern Kingdoms                        │
│                                                                              │
│  ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐   │
│  │  0,0    │  1,0    │  2,0    │  3,0    │  4,0    │  5,0    │  6,0    │   │
│  │ (Node1) │ (Node1) │ (Node2) │ (Node2) │ (Node3) │ (Node3) │ (Node3) │   │
│  ├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤   │
│  │  0,1    │  1,1    │  2,1    │  3,1    │  4,1    │  5,1    │  6,1    │   │
│  │ (Node1) │ (Node1) │ (Node2) │ (Node2) │ (Node3) │ (Node3) │ (Node4) │   │
│  ├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤   │
│  │  0,2    │  1,2    │  2,2    │  3,2    │  4,2    │  5,2    │  6,2    │   │
│  │ (Node1) │ (Node1) │ (Node2) │ (Node2) │ (Node4) │ (Node4) │ (Node4) │   │
│  ├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤   │
│  │  ...    │  ...    │  ...    │  ...    │  ...    │  ...    │  ...    │   │
│  └─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘   │
│                                                                              │
│  Cell dimensions: 533.33 yards x 533.33 yards (1/64 of map)                 │
│  Cells per continent: 64 x 64 = 4,096                                       │
│  Total cells (all continents): ~20,000                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cell Data Structure

```cpp
struct CellId {
    uint16_t continent_id;  // 0 = Eastern Kingdoms, 1 = Kalimdor, etc.
    uint8_t  x;             // 0-63
    uint8_t  y;             // 0-63
    uint8_t  level;         // 0 = base, 1-4 = subdivisions

    // Unique 64-bit identifier
    uint64_t to_u64() const {
        return (uint64_t(continent_id) << 48) |
               (uint64_t(x) << 40) |
               (uint64_t(y) << 32) |
               (uint64_t(level) << 24);
    }
};

struct CellState {
    CellId id;
    NodeId owner_node;

    // Boundaries (world coordinates)
    float min_x, max_x;
    float min_y, max_y;

    // Entity tracking
    std::vector<EntityId> entities;
    SpatialHash<EntityId> spatial_index;  // For fast range queries

    // Neighbor cells (for boundary interactions)
    std::array<CellId, 8> neighbors;  // N, NE, E, SE, S, SW, W, NW

    // Load metrics
    uint32_t entity_count;
    uint32_t events_per_second;
    float    cpu_utilization;

    // Versioning
    uint64_t version;
    VectorClock clock;
};
```

## Cell Assignment

### Initial Assignment Algorithm

When the cluster starts, cells are distributed evenly:

```
Algorithm: BalancedCellAssignment

Input: cells[], nodes[]
Output: assignment map (cell -> node)

1. Sort cells by expected load (based on historical data or map features)
2. Sort nodes by capacity (CPU cores, memory)
3. Use round-robin assignment with load balancing:

   for each cell in cells:
       node = node with lowest current_load
       assign(cell, node)
       node.current_load += cell.expected_load
```

### Assignment Storage

Cell assignments are stored in etcd for cluster-wide consistency:

```
/swarm/cells/0/32/45/0    -> { "node": "zone-node-7", "version": 142 }
/swarm/cells/0/32/46/0    -> { "node": "zone-node-7", "version": 143 }
/swarm/cells/1/10/20/0    -> { "node": "zone-node-12", "version": 89 }
```

## Dynamic Cell Splitting

When a cell becomes overloaded (hot spot), it can be split into smaller sub-cells:

### Before Split (Stormwind - Heavy Load)

```
┌─────────────────────────────────────┐
│                                     │
│           Cell (24, 32)             │
│           Level: 0                  │
│                                     │
│      Entities: 50,000               │
│      Events/sec: 100,000            │
│      CPU: 95% (OVERLOADED)          │
│                                     │
│           Owner: Node 3             │
│                                     │
└─────────────────────────────────────┘
```

### After Split (4-way subdivision)

```
┌─────────────────┬─────────────────┐
│                 │                 │
│  Cell (24,32)   │  Cell (24,32)   │
│  Level: 1       │  Level: 1       │
│  Quadrant: NW   │  Quadrant: NE   │
│                 │                 │
│  Entities: 8K   │  Entities: 12K  │
│  Owner: Node 3  │  Owner: Node 7  │
│                 │                 │
├─────────────────┼─────────────────┤
│                 │                 │
│  Cell (24,32)   │  Cell (24,32)   │
│  Level: 1       │  Level: 1       │
│  Quadrant: SW   │  Quadrant: SE   │
│                 │                 │
│  Entities: 15K  │  Entities: 15K  │
│  Owner: Node 3  │  Owner: Node 9  │
│                 │                 │
└─────────────────┴─────────────────┘
```

### Split Algorithm

```
Algorithm: CellSplit

Trigger: cell.cpu_utilization > 80% for 60 seconds

1. Coordinator receives overload notification
2. Select target nodes for new sub-cells:
   - Prefer nodes with low utilization
   - Prefer nodes in same availability zone (latency)

3. Create sub-cell definitions:
   for quadrant in [NW, NE, SW, SE]:
       sub_cell = Cell{
           id: parent.id with level+1 and quadrant,
           bounds: calculate_quadrant_bounds(parent, quadrant),
           owner: selected_node[quadrant]
       }

4. Prepare migration:
   - Freeze parent cell (no new actions)
   - Classify entities by destination sub-cell

5. Execute migration:
   for each entity in parent.entities:
       destination = determine_sub_cell(entity.position)
       migrate(entity, destination)

6. Activate sub-cells:
   - Mark parent as "split"
   - Enable sub-cells for processing

7. Update routing:
   - Notify all nodes of new cell structure
```

### Merge Algorithm (Reverse)

When load decreases, sub-cells can be merged back:

```
Trigger: All sub-cells.cpu_utilization < 20% for 300 seconds

1. Select target node for merged cell
2. Migrate all entities to target
3. Deactivate sub-cells
4. Activate parent cell
```

## Boundary Handling

Entities near cell boundaries require special handling for interactions.

### Interest Zone

Each cell maintains awareness of entities in a **boundary zone** of neighboring cells:

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  ┌─────────────────┐     ┌─────────────────┐                │
│  │   Cell A        │     │   Cell B        │                │
│  │   (Node 1)      │     │   (Node 2)      │                │
│  │                 │     │                 │                │
│  │           ┌─────┼─────┼─────┐           │                │
│  │           │ ////│/////│//// │           │                │
│  │           │ ////│/////│//// │           │                │
│  │           │ ////│/////│//// │           │                │
│  │           └─────┼─────┼─────┘           │                │
│  │                 │     │                 │                │
│  └─────────────────┘     └─────────────────┘                │
│                                                              │
│  //// = Boundary zone (40 yards on each side)               │
│        Entities here are replicated to both cells           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Boundary Zone Protocol

```cpp
const float BOUNDARY_ZONE_SIZE = 40.0f;  // yards

bool is_in_boundary_zone(Entity& e, Cell& cell) {
    return (e.position.x < cell.min_x + BOUNDARY_ZONE_SIZE) ||
           (e.position.x > cell.max_x - BOUNDARY_ZONE_SIZE) ||
           (e.position.y < cell.min_y + BOUNDARY_ZONE_SIZE) ||
           (e.position.y > cell.max_y - BOUNDARY_ZONE_SIZE);
}

// When entity enters boundary zone:
void on_enter_boundary_zone(Entity& e, Cell& cell) {
    for (CellId neighbor : cell.neighbors) {
        if (overlaps_boundary(e.position, neighbor)) {
            send_entity_shadow(e, neighbor);
        }
    }
}

// Shadow = read-only replica for visibility/targeting
struct EntityShadow {
    EntityId id;
    CellId   home_cell;    // Authoritative cell
    Position position;
    uint32_t health;
    uint32_t faction;
    // Minimal state for visibility/targeting
};
```

### Cross-Boundary Interactions

When Bot A (Cell 1) wants to attack Player B (Cell 2):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Cross-Boundary Combat Protocol                           │
│                                                                              │
│   Cell 1 (Node A)              Coordinator              Cell 2 (Node B)     │
│        │                           │                           │             │
│        │  Bot A: "Attack B"        │                           │             │
│        │──────────────────────────►│                           │             │
│        │                           │                           │             │
│        │                           │  Forward attack request   │             │
│        │                           │──────────────────────────►│             │
│        │                           │                           │             │
│        │                           │         Validate:         │             │
│        │                           │    - Is B in range?       │             │
│        │                           │    - Is B valid target?   │             │
│        │                           │    - Calculate damage     │             │
│        │                           │                           │             │
│        │                           │  Combat result            │             │
│        │                           │◄──────────────────────────│             │
│        │                           │                           │             │
│        │  Combat result            │                           │             │
│        │◄──────────────────────────│                           │             │
│        │                           │                           │             │
│        │  Update Bot A state       │  Update Player B state    │             │
│                                                                              │
│  Latency: ~10-20ms (same region)                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Zone Node Responsibilities

Each Zone Node is responsible for:

### 1. Entity Authority
- Authoritative state for all entities in owned cells
- Process actions (movement, combat, spells)
- Validate incoming action requests

### 2. State Publication
- Publish entity updates to Message Bus
- Maintain list of subscribers (Bot Compute Nodes, neighboring cells)
- Rate-limit updates for non-critical state

### 3. Cell Management
- Monitor cell load metrics
- Report to Coordinator for rebalancing decisions
- Execute cell splits/merges
- Handle entity migrations

### 4. Event Logging
- Write all state changes to Kafka
- Maintain local checkpoint for recovery

## Load Metrics

### Metrics Collected Per Cell

| Metric | Description | Collection Interval |
|--------|-------------|-------------------|
| `entity_count` | Number of entities in cell | 1 second |
| `events_per_second` | State change events | 1 second |
| `cpu_utilization` | Processing time / wall time | 1 second |
| `boundary_crossings` | Entities crossing boundaries | 10 seconds |
| `cross_cell_interactions` | Actions involving other cells | 10 seconds |
| `memory_usage` | Cell state memory | 30 seconds |

### Load Balancing Triggers

| Condition | Action |
|-----------|--------|
| `cpu > 80%` for 60s | Split cell |
| `cpu < 20%` for 300s | Consider merge |
| `entity_count > 100,000` | Split cell |
| Node failure | Reassign cells |

## Instanced Content

Dungeons and raids use separate instance cells:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Instance Cell Handling                             │
│                                                                              │
│  Open World Cells (shared):                                                  │
│  ┌─────────┬─────────┬─────────┐                                            │
│  │ Cell A  │ Cell B  │ Cell C  │  ← Many players/bots share these           │
│  └─────────┴─────────┴─────────┘                                            │
│                                                                              │
│  Instance Cells (isolated):                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Instance Pool: Deadmines                                            │   │
│  │                                                                       │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐               │   │
│  │  │ Inst-1  │  │ Inst-2  │  │ Inst-3  │  │ Inst-N  │  ...          │   │
│  │  │ Group A │  │ Group B │  │ Group C │  │ Group N │               │   │
│  │  │ Node 5  │  │ Node 5  │  │ Node 7  │  │ Node 7  │               │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘               │   │
│  │                                                                       │   │
│  │  Each instance is a separate cell with:                              │   │
│  │  - Isolated entity namespace                                          │   │
│  │  - Single Zone Node ownership                                         │   │
│  │  - No boundary sharing                                                │   │
│  │  - Lifecycle: created on enter, destroyed when empty                 │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Instance Allocation

```cpp
struct InstanceRequest {
    uint32_t map_id;       // Dungeon/raid map
    uint32_t difficulty;
    GroupId  group_id;
};

InstanceCell* allocate_instance(InstanceRequest& req) {
    // Find node with capacity
    NodeId node = find_node_with_capacity(req.map_id);

    // Create isolated cell
    CellId cell_id = generate_instance_cell_id(req.map_id, req.group_id);

    // Initialize instance state
    InstanceCell* cell = new InstanceCell{
        .id = cell_id,
        .owner = node,
        .map_id = req.map_id,
        .group_id = req.group_id,
        .created_at = now(),
        .entities = spawn_instance_npcs(req.map_id)
    };

    return cell;
}
```

## Configuration

### Cell Configuration (etcd)

```yaml
# /swarm/config/cells
cells:
  base_size: 533.33        # yards (1/64 of map)
  max_split_level: 4       # Maximum subdivision depth (16x16 sub-cells)
  boundary_zone: 40.0      # yards

  load_thresholds:
    split_cpu: 80          # % CPU to trigger split
    split_entities: 100000 # Entity count to trigger split
    merge_cpu: 20          # % CPU to consider merge
    merge_cooldown: 300    # seconds after split before merge allowed

  metrics:
    collection_interval: 1000   # ms
    report_interval: 5000       # ms
```

## Next Steps

- [03-entity-management.md](03-entity-management.md) - Entity state and migration
- [05-communication.md](05-communication.md) - Inter-node messaging
