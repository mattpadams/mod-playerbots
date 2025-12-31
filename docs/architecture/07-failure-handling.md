# Failure Handling

This document describes how Swarm handles various failure scenarios to maintain availability and data integrity.

## Failure Categories

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Failure Taxonomy                                     │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Node Failures                                 │   │
│  │                                                                       │   │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐        │   │
│  │  │   Crash   │  │  Hang/    │  │  Network  │  │   Slow    │        │   │
│  │  │   Stop    │  │  Freeze   │  │ Partition │  │   Node    │        │   │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘        │   │
│  │                                                                       │   │
│  │  Recovery:      Detection:     Handling:      Detection:            │   │
│  │  - Replace      - Timeout      - Fencing      - Latency             │   │
│  │  - Replay       - Heartbeat    - Quorum       - Metrics             │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Data Failures                                  │   │
│  │                                                                       │   │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐        │   │
│  │  │   Lost    │  │ Corrupted │  │  Stale    │  │ Duplicate │        │   │
│  │  │  Message  │  │   Data    │  │   Data    │  │  Message  │        │   │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘        │   │
│  │                                                                       │   │
│  │  Recovery:      Detection:     Resolution:    Handling:             │   │
│  │  - Retry        - Checksum     - Version      - Dedup               │   │
│  │  - Replay       - Validation   - Timestamp    - Idempotency         │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Node Failure Detection

### Heartbeat Protocol

```cpp
class HeartbeatMonitor {
    static const auto HEARTBEAT_INTERVAL = std::chrono::milliseconds(500);
    static const auto FAILURE_THRESHOLD = std::chrono::seconds(3);

    std::map<NodeId, std::chrono::steady_clock::time_point> last_heartbeat;
    std::set<NodeId> suspected_nodes;

public:
    void receive_heartbeat(NodeId node) {
        last_heartbeat[node] = std::chrono::steady_clock::now();
        suspected_nodes.erase(node);
    }

    void check_nodes() {
        auto now = std::chrono::steady_clock::now();

        for (auto& [node, last_seen] : last_heartbeat) {
            auto elapsed = now - last_seen;

            if (elapsed > FAILURE_THRESHOLD) {
                if (!suspected_nodes.contains(node)) {
                    suspected_nodes.insert(node);
                    on_node_suspected(node);
                }
            }
        }
    }

    void on_node_suspected(NodeId node) {
        // Start failure confirmation process
        // Multiple coordinators must agree before declaring failure
        initiate_failure_vote(node);
    }
};
```

### Failure Confirmation (Quorum)

```cpp
class FailureConfirmation {
    std::map<NodeId, std::set<NodeId>> failure_votes;  // suspected -> voters

    static const int QUORUM_SIZE = 3;  // Majority of coordinators

public:
    void vote_failure(NodeId suspected, NodeId voter) {
        failure_votes[suspected].insert(voter);

        if (failure_votes[suspected].size() >= QUORUM_SIZE) {
            // Confirmed failure
            confirm_node_failure(suspected);
        }
    }

    void confirm_node_failure(NodeId node) {
        // Fence the node (prevent split-brain)
        fence_node(node);

        // Reassign its cells
        reassign_cells(node);

        // Notify all nodes
        broadcast_failure_notification(node);
    }
};
```

## Zone Node Failure

### Cell Reassignment Procedure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Zone Node Failure Recovery                                │
│                                                                              │
│   Timeline                                                                   │
│   ────────────────────────────────────────────────────────────────────────  │
│   T+0s     │ Node X stops responding                                        │
│            │                                                                 │
│   T+3s     │ Heartbeat timeout - suspected failure                          │
│            │ Coordinators begin voting                                       │
│            │                                                                 │
│   T+4s     │ Quorum reached - failure confirmed                             │
│            │ Node X fenced (removed from cluster membership)                │
│            │                                                                 │
│   T+4.5s   │ Cell reassignment begins                                       │
│            │ ┌─────────────────────────────────────────────────────────┐   │
│            │ │  Node X owned: [Cell A, Cell B, Cell C]                 │   │
│            │ │                                                          │   │
│            │ │  Reassignment:                                           │   │
│            │ │  - Cell A → Node Y (lowest load)                        │   │
│            │ │  - Cell B → Node Z (same availability zone)             │   │
│            │ │  - Cell C → Node Y                                       │   │
│            │ └─────────────────────────────────────────────────────────┘   │
│            │                                                                 │
│   T+5s     │ New owners begin state recovery                                │
│            │ - Replay events from Kafka                                     │
│            │ - Query entity registry for current positions                  │
│            │                                                                 │
│   T+10-30s │ State recovery complete                                        │
│            │ Cells become active                                            │
│            │                                                                 │
│   T+30s    │ Full recovery - normal operation                               │
│            │                                                                 │
│   Impact:  │ Entities in affected cells frozen for ~10-30 seconds          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### State Recovery Algorithm

```cpp
class StateRecovery {
public:
    void recover_cell(CellId cell, NodeId previous_owner) {
        // 1. Find last checkpoint for this cell
        auto checkpoint = state_store.get_latest_checkpoint(cell);

        // 2. Load checkpoint state
        CellState state;
        if (checkpoint) {
            state = load_checkpoint(checkpoint);
        } else {
            state = CellState{};
        }

        // 3. Replay events since checkpoint
        uint64_t from_sequence = checkpoint ? checkpoint->sequence : 0;
        auto events = event_log.read_events(cell, from_sequence);

        for (const auto& event : events) {
            apply_event(state, event);
        }

        // 4. Query entity registry for entities that might have migrated
        auto registry_entities = entity_registry.get_entities_in_cell(cell);

        for (EntityId entity : registry_entities) {
            if (!state.has_entity(entity)) {
                // Entity migrated to us but we don't have it
                auto entity_state = fetch_entity_state(entity, previous_owner);
                if (entity_state) {
                    state.add_entity(*entity_state);
                }
            }
        }

        // 5. Activate cell
        activate_cell(cell, state);
    }

private:
    std::optional<EntityState> fetch_entity_state(EntityId entity, NodeId prev) {
        // Try to get from other nodes that might have replicas
        for (NodeId node : get_neighbor_nodes(prev)) {
            auto state = rpc_call(node, "get_entity_shadow", entity);
            if (state) return state;
        }
        return std::nullopt;
    }
};
```

## Bot Compute Node Failure

Bot Compute Node failures are less critical since they don't hold authoritative state:

```cpp
class BotComputeFailureHandler {
public:
    void handle_failure(NodeId failed_node) {
        // 1. Get list of bots assigned to failed node
        auto bots = get_bots_assigned_to(failed_node);

        // 2. Redistribute to healthy nodes
        auto healthy_nodes = get_healthy_bot_compute_nodes();

        for (EntityId bot : bots) {
            NodeId new_node = select_node_with_lowest_load(healthy_nodes);
            reassign_bot(bot, new_node);

            // Bot AI state is stateless - will reinitialize
        }

        // 3. No state recovery needed - AI state reconstructs from world view
        // Bots may be "confused" for one AI tick but will recover
    }
};
```

## Network Partition Handling

### Split-Brain Prevention

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Network Partition Scenario                                │
│                                                                              │
│  ┌─────────────────────────┐    PARTITION    ┌─────────────────────────┐   │
│  │      Partition A        │        ║        │      Partition B        │   │
│  │                         │        ║        │                         │   │
│  │  Zone Node 1            │        ║        │  Zone Node 3            │   │
│  │  Zone Node 2            │        ║        │  Zone Node 4            │   │
│  │  Coordinator 1          │        ║        │  Coordinator 2          │   │
│  │  Coordinator 2          │        ║        │                         │   │
│  │                         │        ║        │                         │   │
│  │  Has quorum (3/5)       │        ║        │  No quorum (2/5)        │   │
│  │  CONTINUES OPERATING    │        ║        │  STOPS ACCEPTING WRITES │   │
│  │                         │        ║        │                         │   │
│  └─────────────────────────┘        ║        └─────────────────────────┘   │
│                                     ║                                       │
│  Resolution:                        ║                                       │
│  - Partition B becomes read-only    ║                                       │
│  - Entities in Partition B frozen   ║                                       │
│  - When partition heals, B rejoins  ║                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Fencing Mechanism

```cpp
class FencingToken {
    uint64_t epoch;
    NodeId holder;
    std::chrono::steady_clock::time_point expires;

public:
    bool is_valid() const {
        return std::chrono::steady_clock::now() < expires;
    }
};

class CellFencing {
    std::map<CellId, FencingToken> cell_tokens;

public:
    // Before processing, check if we hold valid token
    bool can_process_cell(CellId cell, NodeId node) {
        if (!cell_tokens.contains(cell)) {
            return false;
        }

        auto& token = cell_tokens[cell];
        return token.is_valid() && token.holder == node;
    }

    // Acquire token (requires coordinator quorum)
    std::optional<FencingToken> acquire_token(CellId cell, NodeId node) {
        // Request from coordinator cluster
        auto response = coordinator.request_cell_token(cell, node);

        if (response.granted) {
            FencingToken token{
                .epoch = response.epoch,
                .holder = node,
                .expires = std::chrono::steady_clock::now() +
                          std::chrono::seconds(30)
            };
            cell_tokens[cell] = token;
            return token;
        }

        return std::nullopt;
    }

    // Periodically renew tokens
    void renew_tokens() {
        for (auto& [cell, token] : cell_tokens) {
            if (should_renew(token)) {
                auto new_token = acquire_token(cell, token.holder);
                if (new_token) {
                    token = *new_token;
                } else {
                    // Lost ownership - stop processing
                    release_cell(cell);
                }
            }
        }
    }
};
```

## Message Failure Handling

### Retry with Exponential Backoff

```cpp
class MessageRetry {
    static const int MAX_RETRIES = 5;
    static const auto BASE_DELAY = std::chrono::milliseconds(100);

public:
    template<typename T>
    std::optional<T> send_with_retry(NodeId target, const Message& msg) {
        for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
            try {
                return send(target, msg);
            } catch (const NetworkException& e) {
                if (attempt == MAX_RETRIES - 1) {
                    throw;  // Final attempt failed
                }

                auto delay = BASE_DELAY * (1 << attempt);  // Exponential backoff
                delay += random_jitter(delay);  // Add jitter
                std::this_thread::sleep_for(delay);
            }
        }
        return std::nullopt;
    }

private:
    std::chrono::milliseconds random_jitter(std::chrono::milliseconds base) {
        static std::mt19937 rng(std::random_device{}());
        std::uniform_int_distribution<int> dist(0, base.count() / 2);
        return std::chrono::milliseconds(dist(rng));
    }
};
```

### Idempotency for Action Requests

```cpp
class IdempotentActionProcessor {
    LRUCache<uint64_t, ActionResult> processed_requests;

public:
    ActionResult process_action(const ActionRequest& request) {
        // Check if already processed
        if (auto cached = processed_requests.get(request.request_id)) {
            return *cached;  // Return cached result
        }

        // Process the action
        ActionResult result = execute_action(request);

        // Cache the result
        processed_requests.put(request.request_id, result);

        return result;
    }
};
```

## Graceful Degradation

### Load Shedding

```cpp
class LoadShedder {
    std::atomic<float> current_load{0.0f};

    static const float SOFT_LIMIT = 0.8f;
    static const float HARD_LIMIT = 0.95f;

public:
    bool should_accept(RequestPriority priority) {
        float load = current_load.load();

        if (load > HARD_LIMIT) {
            // Only accept critical requests
            return priority == RequestPriority::CRITICAL;
        }

        if (load > SOFT_LIMIT) {
            // Probabilistic shedding based on priority
            float accept_probability = 1.0f - (load - SOFT_LIMIT) / (HARD_LIMIT - SOFT_LIMIT);
            accept_probability *= priority_factor(priority);

            return random_float() < accept_probability;
        }

        return true;  // Accept all
    }

private:
    float priority_factor(RequestPriority p) {
        switch (p) {
            case RequestPriority::CRITICAL: return 1.0f;
            case RequestPriority::HIGH: return 0.8f;
            case RequestPriority::NORMAL: return 0.5f;
            case RequestPriority::LOW: return 0.2f;
        }
    }
};
```

### Circuit Breaker

```cpp
class CircuitBreaker {
    enum class State { CLOSED, OPEN, HALF_OPEN };

    State state = State::CLOSED;
    int failure_count = 0;
    std::chrono::steady_clock::time_point last_failure;

    static const int FAILURE_THRESHOLD = 5;
    static const auto OPEN_DURATION = std::chrono::seconds(30);

public:
    bool can_proceed() {
        switch (state) {
            case State::CLOSED:
                return true;

            case State::OPEN:
                if (std::chrono::steady_clock::now() - last_failure > OPEN_DURATION) {
                    state = State::HALF_OPEN;
                    return true;  // Allow one request through
                }
                return false;

            case State::HALF_OPEN:
                return true;  // Allow request to test
        }
    }

    void record_success() {
        if (state == State::HALF_OPEN) {
            state = State::CLOSED;
            failure_count = 0;
        }
    }

    void record_failure() {
        failure_count++;
        last_failure = std::chrono::steady_clock::now();

        if (failure_count >= FAILURE_THRESHOLD) {
            state = State::OPEN;
        }
    }
};
```

## Disaster Recovery

### Multi-Region Failover

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Multi-Region Disaster Recovery                            │
│                                                                              │
│  Normal Operation:                                                           │
│  ┌─────────────────────────┐     ┌─────────────────────────┐               │
│  │      US-East (Primary)  │────►│    EU-West (Standby)    │               │
│  │                         │     │                         │               │
│  │  Zone Nodes: Active     │ Async│  Zone Nodes: Hot standby│               │
│  │  Bot Compute: Active    │ Repl │  Bot Compute: Warm      │               │
│  │  Event Log: Writing     │     │  Event Log: Replicated  │               │
│  └─────────────────────────┘     └─────────────────────────┘               │
│                                                                              │
│  Failover Procedure:                                                        │
│  1. Detect primary region failure (monitoring, heartbeats)                  │
│  2. Promote EU-West to primary (manual or automatic)                        │
│  3. Replay any unreplicated events (RPO: ~seconds)                         │
│  4. Activate standby nodes                                                  │
│  5. Update DNS/routing to new primary                                       │
│  6. Resume operations (RTO: ~5 minutes)                                     │
│                                                                              │
│  RPO (Recovery Point Objective): < 10 seconds of data loss                  │
│  RTO (Recovery Time Objective): < 5 minutes to full recovery               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Backup and Restore

```cpp
class BackupManager {
public:
    // Create snapshot of all state
    void create_backup() {
        // 1. Signal all Zone Nodes to checkpoint
        for (NodeId node : get_zone_nodes()) {
            rpc_call(node, "create_checkpoint");
        }

        // 2. Export Kafka topics to blob storage
        for (const auto& topic : event_topics) {
            export_topic_to_s3(topic);
        }

        // 3. Export ScyllaDB tables
        export_scylladb_snapshot();

        // 4. Record backup metadata
        BackupMetadata meta{
            .timestamp = now(),
            .kafka_offsets = get_current_offsets(),
            .checkpoint_ids = get_checkpoint_ids()
        };
        save_metadata(meta);
    }

    // Restore from backup
    void restore_from_backup(const BackupMetadata& backup) {
        // 1. Stop all nodes
        shutdown_cluster();

        // 2. Restore ScyllaDB
        restore_scylladb_snapshot(backup);

        // 3. Restore Kafka topics
        for (const auto& topic : event_topics) {
            import_topic_from_s3(topic, backup);
        }

        // 4. Start nodes and replay from checkpoints
        start_cluster_with_recovery(backup.checkpoint_ids);
    }
};
```

## Monitoring and Alerting

### Health Checks

```cpp
struct HealthStatus {
    enum class Level { HEALTHY, DEGRADED, UNHEALTHY };

    Level level;
    std::string message;
    std::map<std::string, std::string> details;
};

class HealthChecker {
public:
    HealthStatus check() {
        HealthStatus status{HealthStatus::Level::HEALTHY, "OK", {}};

        // Check message bus connectivity
        if (!check_nats_connection()) {
            status.level = HealthStatus::Level::UNHEALTHY;
            status.details["nats"] = "disconnected";
        }

        // Check event log
        if (!check_kafka_connection()) {
            status.level = HealthStatus::Level::UNHEALTHY;
            status.details["kafka"] = "disconnected";
        }

        // Check coordinator quorum
        if (!check_coordinator_quorum()) {
            status.level = HealthStatus::Level::DEGRADED;
            status.details["coordinator"] = "no quorum";
        }

        // Check cell ownership
        if (has_orphaned_cells()) {
            status.level = HealthStatus::Level::DEGRADED;
            status.details["cells"] = "orphaned cells detected";
        }

        return status;
    }
};
```

### Alerting Rules

```yaml
# alerting-rules.yaml
groups:
  - name: swarm-critical
    rules:
      - alert: NodeDown
        expr: up{job="zone-node"} == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Zone node {{ $labels.instance }} is down"

      - alert: CoordinatorQuorumLost
        expr: coordinator_quorum_size < 3
        for: 10s
        labels:
          severity: critical
        annotations:
          summary: "Coordinator quorum lost"

      - alert: HighEventLag
        expr: kafka_consumer_lag > 10000
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Event processing lag is high"

      - alert: CellRecoveryStalled
        expr: cell_recovery_duration_seconds > 60
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Cell recovery taking too long"
```

## Next Steps

- [08-scaling.md](08-scaling.md) - Capacity planning for resilience
- [06-consistency.md](06-consistency.md) - How failures affect consistency
