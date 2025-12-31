# Distributed Consistency

This document describes the consistency models used in Swarm and how data synchronization is maintained across the cluster.

## Consistency Spectrum

Different types of data require different consistency guarantees:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Consistency Spectrum                                  │
│                                                                              │
│  Strong ◄────────────────────────────────────────────────────► Eventual     │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Linearizable │  │   Causal     │  │   Session    │  │  Eventual    │    │
│  │              │  │              │  │              │  │              │    │
│  │ - Gold/items │  │ - Combat     │  │ - Quest      │  │ - Positions  │    │
│  │ - Trades     │  │   sequences  │  │   progress   │  │ - Health     │    │
│  │ - Cell owner │  │ - Spell      │  │ - XP         │  │ - Buffs      │    │
│  │              │  │   effects    │  │              │  │              │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                                              │
│  Latency:  ~10-50ms        ~5-20ms        ~5-10ms         ~1-5ms           │
│  Throughput: Lower ◄──────────────────────────────────────► Higher         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Consistency Levels by Data Type

| Data Type | Consistency | Rationale |
|-----------|-------------|-----------|
| Entity ownership | Strong (Raft) | Must never have two owners |
| Gold/inventory | Strong | Prevents duplication exploits |
| Cell assignments | Strong | Cluster-wide agreement needed |
| Combat damage | Causal | Damage must follow attack |
| Spell effects | Causal | Effect must follow cast |
| Quest progress | Session | User sees their own updates |
| Positions | Eventual | High frequency, tolerates lag |
| Health/mana | Eventual | Frequent updates, ~50ms lag OK |
| Buffs/debuffs | Eventual | Can lag slightly |

## Strong Consistency (Raft)

Used for critical state that must never diverge.

### Implementation

```cpp
// Raft-based consensus for cell ownership
class CellOwnershipService {
    RaftNode raft;

public:
    // Returns only after majority acknowledgment
    bool assign_cell(CellId cell, NodeId node) {
        CellAssignment cmd{cell, node, now()};
        return raft.propose(cmd).wait();  // Blocks until committed
    }

    NodeId get_owner(CellId cell) {
        // Read from local state machine (after sync)
        return raft.state_machine().get_cell_owner(cell);
    }
};
```

### Trade Protocol (Strong Consistency)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Trade Protocol (Two-Phase Commit)                         │
│                                                                              │
│   Bot A Node           Coordinator           Player B Node                  │
│       │                     │                      │                         │
│       │  1. TradeRequest    │                      │                         │
│       │────────────────────►│                      │                         │
│       │                     │  2. PrepareA         │                         │
│       │◄────────────────────│                      │                         │
│       │                     │                      │                         │
│   ┌───┴───┐                 │                      │                         │
│   │ Lock  │                 │                      │                         │
│   │ items │                 │                      │                         │
│   └───┬───┘                 │                      │                         │
│       │                     │                      │                         │
│       │  3. PreparedA       │                      │                         │
│       │────────────────────►│                      │                         │
│       │                     │  4. PrepareB         │                         │
│       │                     │─────────────────────►│                         │
│       │                     │                      │                         │
│       │                     │                 ┌────┴────┐                    │
│       │                     │                 │  Lock   │                    │
│       │                     │                 │  items  │                    │
│       │                     │                 └────┬────┘                    │
│       │                     │                      │                         │
│       │                     │  5. PreparedB        │                         │
│       │                     │◄─────────────────────│                         │
│       │                     │                      │                         │
│       │                ┌────┴────┐                 │                         │
│       │                │ Decide  │                 │                         │
│       │                │ COMMIT  │                 │                         │
│       │                └────┬────┘                 │                         │
│       │                     │                      │                         │
│       │  6. Commit          │  6. Commit           │                         │
│       │◄────────────────────│─────────────────────►│                         │
│       │                     │                      │                         │
│   ┌───┴───┐                 │                 ┌────┴────┐                    │
│   │Execute│                 │                 │ Execute │                    │
│   │ trade │                 │                 │  trade  │                    │
│   └───┬───┘                 │                 └────┬────┘                    │
│       │                     │                      │                         │
│       │  7. Ack             │  7. Ack              │                         │
│       │────────────────────►│◄─────────────────────│                         │
│       │                     │                      │                         │
│                                                                              │
│  If any Prepare fails: ABORT and rollback                                   │
│  Timeout on any step: ABORT and rollback                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Causal Consistency

Ensures that causally related events are seen in the correct order.

### Vector Clocks

```cpp
struct VectorClock {
    std::map<NodeId, uint64_t> clock;

    // Increment local counter on each event
    void tick(NodeId node) {
        clock[node]++;
    }

    // Merge with incoming clock
    void merge(const VectorClock& other) {
        for (auto& [node, time] : other.clock) {
            clock[node] = std::max(clock[node], time);
        }
    }

    // Check if this happened-before other
    bool happened_before(const VectorClock& other) const {
        bool dominated = false;
        for (auto& [node, time] : clock) {
            auto it = other.clock.find(node);
            uint64_t other_time = (it != other.clock.end()) ? it->second : 0;
            if (time > other_time) return false;
            if (time < other_time) dominated = true;
        }
        return dominated;
    }

    // Check if concurrent (neither happened-before the other)
    bool concurrent_with(const VectorClock& other) const {
        return !happened_before(other) && !other.happened_before(*this);
    }
};
```

### Combat Causality

```cpp
// Ensure damage is applied in causal order
class CausalCombatProcessor {
    std::map<EntityId, std::priority_queue<CombatEvent, CausalOrder>> pending;

public:
    void receive_event(const CombatEvent& event) {
        // Check if all causal dependencies are satisfied
        if (has_all_dependencies(event)) {
            apply_event(event);
            process_waiting_events(event.target);
        } else {
            // Queue until dependencies arrive
            pending[event.target].push(event);
        }
    }

private:
    bool has_all_dependencies(const CombatEvent& event) {
        // Event's vector clock must be ≤ our current clock for that entity
        auto& entity_clock = entity_clocks[event.target];
        return event.clock.happened_before(entity_clock) ||
               event.clock == entity_clock;
    }

    void apply_event(const CombatEvent& event) {
        // Apply damage, update health, etc.
        switch (event.type) {
            case CombatEventType::DAMAGE:
                apply_damage(event.target, event.damage, event.source);
                break;
            case CombatEventType::HEAL:
                apply_heal(event.target, event.amount, event.source);
                break;
            // ...
        }

        // Update entity's clock
        entity_clocks[event.target].merge(event.clock);
    }
};
```

## Eventual Consistency with CRDTs

For high-frequency data like positions, we use Conflict-free Replicated Data Types.

### Position CRDT (Last-Writer-Wins Register)

```cpp
// LWW Register for position - highest timestamp wins
struct PositionLWW {
    Position value;
    uint64_t timestamp;
    NodeId writer;

    void update(Position new_value, uint64_t ts, NodeId node) {
        if (ts > timestamp || (ts == timestamp && node > writer)) {
            value = new_value;
            timestamp = ts;
            writer = node;
        }
    }

    void merge(const PositionLWW& other) {
        if (other.timestamp > timestamp ||
            (other.timestamp == timestamp && other.writer > writer)) {
            value = other.value;
            timestamp = other.timestamp;
            writer = other.writer;
        }
    }
};
```

### Health CRDT (Bounded Counter)

```cpp
// Bounded counter for health - allows concurrent damage/healing
struct HealthCRDT {
    struct Delta {
        int32_t amount;
        uint64_t timestamp;
        NodeId source;
    };

    uint32_t base_value;      // Last checkpointed value
    uint32_t max_health;
    std::vector<Delta> deltas;

    uint32_t current_value() const {
        int64_t result = base_value;
        for (const auto& d : deltas) {
            result += d.amount;
        }
        return std::clamp<int64_t>(result, 0, max_health);
    }

    void apply_damage(uint32_t amount, uint64_t ts, NodeId source) {
        deltas.push_back({-static_cast<int32_t>(amount), ts, source});
        compact_if_needed();
    }

    void apply_heal(uint32_t amount, uint64_t ts, NodeId source) {
        deltas.push_back({static_cast<int32_t>(amount), ts, source});
        compact_if_needed();
    }

    void merge(const HealthCRDT& other) {
        // Merge deltas, removing duplicates
        for (const auto& d : other.deltas) {
            if (!has_delta(d)) {
                deltas.push_back(d);
            }
        }
        compact_if_needed();
    }

private:
    void compact_if_needed() {
        if (deltas.size() > 100) {
            // Checkpoint: collapse deltas into base_value
            base_value = current_value();
            deltas.clear();
        }
    }
};
```

### Aura Set CRDT (Add-Wins Set)

```cpp
// Add-wins set for buffs/debuffs
struct AuraSetCRDT {
    struct AuraEntry {
        uint32_t spell_id;
        EntityId caster;
        uint64_t applied_at;
        uint64_t expires_at;
        uint8_t stacks;
        bool removed;
        uint64_t removed_at;
    };

    std::map<std::pair<uint32_t, EntityId>, AuraEntry> auras;

    void add_aura(uint32_t spell_id, EntityId caster, uint64_t duration, uint8_t stacks) {
        auto key = std::make_pair(spell_id, caster);
        uint64_t now = current_time();

        auras[key] = AuraEntry{
            .spell_id = spell_id,
            .caster = caster,
            .applied_at = now,
            .expires_at = now + duration,
            .stacks = stacks,
            .removed = false,
            .removed_at = 0
        };
    }

    void remove_aura(uint32_t spell_id, EntityId caster) {
        auto key = std::make_pair(spell_id, caster);
        if (auras.contains(key)) {
            auras[key].removed = true;
            auras[key].removed_at = current_time();
        }
    }

    void merge(const AuraSetCRDT& other) {
        for (const auto& [key, entry] : other.auras) {
            if (!auras.contains(key)) {
                auras[key] = entry;
            } else {
                // Resolve conflict: add wins over remove if add is later
                auto& our = auras[key];
                if (entry.applied_at > our.applied_at) {
                    our = entry;
                } else if (entry.removed && entry.removed_at > our.applied_at) {
                    our.removed = true;
                    our.removed_at = entry.removed_at;
                }
            }
        }
    }

    std::vector<AuraEntry> active_auras() const {
        std::vector<AuraEntry> result;
        uint64_t now = current_time();
        for (const auto& [key, entry] : auras) {
            if (!entry.removed && entry.expires_at > now) {
                result.push_back(entry);
            }
        }
        return result;
    }
};
```

## Conflict Resolution

### Position Conflict (Teleport Detection)

```cpp
struct PositionConflictResolver {
    // When two nodes disagree on position
    Position resolve(const Position& local, const Position& remote,
                    uint64_t local_ts, uint64_t remote_ts) {

        float distance = local.distance_to(remote);

        // Small difference: use latest timestamp
        if (distance < 5.0f) {
            return (remote_ts > local_ts) ? remote : local;
        }

        // Large difference: possible teleport or desync
        // Trust authoritative cell owner
        CellId local_cell = position_to_cell(local);
        CellId remote_cell = position_to_cell(remote);

        if (is_cell_owner(local_cell)) {
            return local;  // We're authoritative
        } else if (is_cell_owner(remote_cell)) {
            return remote;  // They're authoritative
        } else {
            // Neither authoritative - use timestamp
            return (remote_ts > local_ts) ? remote : local;
        }
    }
};
```

### Combat Conflict (Simultaneous Kills)

```cpp
struct CombatConflictResolver {
    // When two attacks simultaneously would kill a target
    void resolve_simultaneous_deaths(
        EntityId target,
        std::vector<DamageEvent>& events) {

        // Sort by timestamp, then by source node ID for determinism
        std::sort(events.begin(), events.end(),
            [](const DamageEvent& a, const DamageEvent& b) {
                if (a.timestamp != b.timestamp)
                    return a.timestamp < b.timestamp;
                return a.source_node < b.source_node;
            });

        uint32_t health = get_health(target);

        for (auto& event : events) {
            if (health == 0) {
                // Already dead - mark as overkill
                event.result = DamageResult::OVERKILL;
                continue;
            }

            if (event.damage >= health) {
                // This is the killing blow
                event.result = DamageResult::KILLING_BLOW;
                health = 0;
            } else {
                event.damage_dealt = event.damage;
                health -= event.damage;
            }
        }
    }
};
```

## Anti-Entropy and Repair

### Gossip Protocol for State Sync

```cpp
class GossipProtocol {
    static const int GOSSIP_FANOUT = 3;
    static const auto GOSSIP_INTERVAL = std::chrono::seconds(1);

    std::map<EntityId, StateDigest> local_digests;

public:
    void gossip_round() {
        // Select random peers
        auto peers = select_random_peers(GOSSIP_FANOUT);

        // Send digests of our state
        for (NodeId peer : peers) {
            send_sync_request(peer, local_digests);
        }
    }

    void handle_sync_request(NodeId from, const std::map<EntityId, StateDigest>& their_digests) {
        std::vector<EntityState> to_send;
        std::vector<EntityId> to_request;

        for (const auto& [entity, their_digest] : their_digests) {
            if (!local_digests.contains(entity)) {
                // We don't have this entity - request it
                to_request.push_back(entity);
            } else if (local_digests[entity].version > their_digest.version) {
                // We have newer - send ours
                to_send.push_back(get_entity_state(entity));
            } else if (local_digests[entity].version < their_digest.version) {
                // They have newer - request theirs
                to_request.push_back(entity);
            }
        }

        // Send our newer states
        if (!to_send.empty()) {
            send_state_update(from, to_send);
        }

        // Request their newer states
        if (!to_request.empty()) {
            send_state_request(from, to_request);
        }
    }
};
```

### Merkle Trees for Efficient Sync

```cpp
class MerkleTree {
    struct Node {
        Hash hash;
        std::unique_ptr<Node> left;
        std::unique_ptr<Node> right;
    };

    std::unique_ptr<Node> root;
    std::map<EntityId, Hash> leaf_hashes;

public:
    // Build tree from entity states
    void rebuild(const std::map<EntityId, EntityState>& entities) {
        leaf_hashes.clear();
        for (const auto& [id, state] : entities) {
            leaf_hashes[id] = hash_state(state);
        }
        root = build_tree(leaf_hashes);
    }

    // Compare with another tree, return differing entity IDs
    std::vector<EntityId> find_differences(const MerkleTree& other) const {
        std::vector<EntityId> diffs;
        find_differences_recursive(root.get(), other.root.get(), diffs);
        return diffs;
    }

private:
    void find_differences_recursive(
        const Node* ours, const Node* theirs, std::vector<EntityId>& diffs) {

        if (ours->hash == theirs->hash) {
            return;  // Subtrees are identical
        }

        if (is_leaf(ours) && is_leaf(theirs)) {
            // Found a difference
            diffs.push_back(get_entity_id(ours));
        } else {
            // Recurse into children
            find_differences_recursive(ours->left.get(), theirs->left.get(), diffs);
            find_differences_recursive(ours->right.get(), theirs->right.get(), diffs);
        }
    }
};
```

## Configuration

```yaml
# consistency.yaml
consistency:
  strong:
    raft_election_timeout_ms: 1000
    raft_heartbeat_interval_ms: 100
    max_pending_proposals: 1000

  causal:
    vector_clock_gc_interval_ms: 60000
    max_pending_events: 10000
    dependency_timeout_ms: 5000

  eventual:
    gossip_interval_ms: 1000
    gossip_fanout: 3
    merkle_rebuild_interval_ms: 30000
    max_clock_drift_ms: 100

  crdt:
    compact_threshold: 100
    checkpoint_interval_ms: 10000
```

## Next Steps

- [07-failure-handling.md](07-failure-handling.md) - How failures affect consistency
- [05-communication.md](05-communication.md) - Message delivery guarantees
