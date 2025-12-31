# Inter-Node Communication

This document describes the messaging architecture for communication between nodes in the Swarm system.

## Overview

Nodes communicate through two primary mechanisms:

1. **Message Bus (NATS)**: Real-time pub/sub for state updates
2. **Event Log (Kafka)**: Durable event stream for persistence and replay

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Communication Architecture                              │
│                                                                              │
│  ┌─────────────┐          ┌─────────────┐          ┌─────────────┐         │
│  │ Zone Node 1 │          │ Zone Node 2 │          │ Zone Node 3 │         │
│  └──────┬──────┘          └──────┬──────┘          └──────┬──────┘         │
│         │                        │                        │                 │
│         │    Real-time Updates   │                        │                 │
│         └────────────┬───────────┴────────────┬───────────┘                 │
│                      │                        │                              │
│                      ▼                        ▼                              │
│         ┌────────────────────────────────────────────────┐                  │
│         │              Message Bus (NATS)                │                  │
│         │                                                 │                  │
│         │   Topics:                                       │                  │
│         │   - cells.{continent}.{x}.{y}  (state updates) │                  │
│         │   - nodes.{node_id}            (direct msgs)   │                  │
│         │   - actions.{zone_node}        (bot actions)   │                  │
│         │   - migrations.{cell_id}       (entity moves)  │                  │
│         │                                                 │                  │
│         └────────────────────────────────────────────────┘                  │
│                      │                        │                              │
│                      ▼                        ▼                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ Bot Compute │  │ Bot Compute │  │ Coordinator │  │  Monitoring │        │
│  │   Node 1    │  │   Node 2    │  │             │  │             │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                              │
│         ┌────────────────────────────────────────────────┐                  │
│         │              Event Log (Kafka)                  │                  │
│         │                                                 │                  │
│         │   Topics:                                       │                  │
│         │   - events.{continent}  (all state changes)    │                  │
│         │   - migrations          (entity transfers)     │                  │
│         │   - errors              (failure events)       │                  │
│         │                                                 │                  │
│         │   Retention: 7 days (configurable)             │                  │
│         │   Partitions: by cell ID                       │                  │
│         │                                                 │                  │
│         └────────────────────────────────────────────────┘                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Message Bus (NATS)

### Topic Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NATS Topic Hierarchy                                 │
│                                                                              │
│  cells.                                                                      │
│  ├── 0.                          # Eastern Kingdoms                          │
│  │   ├── 24.32                   # Cell (24, 32) updates                    │
│  │   ├── 24.33                   # Cell (24, 33) updates                    │
│  │   └── ...                                                                │
│  ├── 1.                          # Kalimdor                                  │
│  │   └── ...                                                                 │
│  └── ...                                                                     │
│                                                                              │
│  nodes.                                                                      │
│  ├── zone-node-1                 # Direct messages to zone-node-1           │
│  ├── zone-node-2                                                            │
│  ├── bot-compute-1                                                          │
│  └── ...                                                                     │
│                                                                              │
│  actions.                                                                    │
│  ├── zone-node-1                 # Bot actions for zone-node-1              │
│  └── ...                                                                     │
│                                                                              │
│  control.                                                                    │
│  ├── migrations                  # Migration coordination                   │
│  ├── rebalance                   # Load balancing signals                   │
│  └── shutdown                    # Graceful shutdown                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Message Types

#### State Update Message

```cpp
// Published by Zone Nodes to cells.{continent}.{x}.{y}
struct StateUpdateMessage {
    MessageType type = MessageType::STATE_UPDATE;
    CellId cell;
    uint64_t tick;
    uint64_t timestamp;

    // Batched entity updates
    std::vector<EntityUpdate> updates;
};

struct EntityUpdate {
    EntityId entity_id;
    UpdateType type;  // POSITION, VITALS, COMBAT, SPAWN, DESPAWN

    // Variant payload based on type
    union {
        PositionUpdate position;
        VitalsUpdate vitals;
        CombatUpdate combat;
        SpawnData spawn;
    };
};

struct PositionUpdate {
    float x, y, z;
    float orientation;
    uint8_t move_flags;
};

struct VitalsUpdate {
    uint32_t health;
    uint32_t power;
    uint8_t alive;
};
```

#### Action Request Message

```cpp
// Published by Bot Compute Nodes to actions.{zone_node}
struct ActionRequestMessage {
    MessageType type = MessageType::ACTION_REQUEST;
    NodeId source_node;
    uint64_t request_id;
    uint64_t tick;

    std::vector<BotAction> actions;
};

struct BotAction {
    EntityId bot_id;
    ActionType action_type;

    union {
        MoveAction move;
        AttackAction attack;
        CastAction cast;
        UseItemAction use_item;
    };
};

struct AttackAction {
    EntityId target;
    uint32_t ability_id;  // 0 for auto-attack
};

struct CastAction {
    uint32_t spell_id;
    EntityId target;
    Position target_position;  // For ground-targeted spells
};
```

#### Action Response Message

```cpp
// Published by Zone Nodes to nodes.{bot_compute_node}
struct ActionResponseMessage {
    MessageType type = MessageType::ACTION_RESPONSE;
    uint64_t request_id;

    std::vector<ActionResult> results;
};

struct ActionResult {
    EntityId bot_id;
    ResultCode code;  // SUCCESS, INVALID_TARGET, OUT_OF_RANGE, ON_COOLDOWN, etc.
    uint64_t next_allowed_tick;  // For rate limiting
};
```

### Subscription Management

```cpp
class MessageBusClient {
    nats::Connection connection;
    std::map<std::string, nats::Subscription> subscriptions;

public:
    // Subscribe to cell updates
    void subscribe_cell(CellId cell, std::function<void(StateUpdateMessage&)> handler) {
        std::string topic = fmt::format("cells.{}.{}.{}",
            cell.continent_id, cell.x, cell.y);

        subscriptions[topic] = connection.subscribe(topic,
            [handler](nats::Message& msg) {
                auto update = deserialize<StateUpdateMessage>(msg.data());
                handler(update);
            });
    }

    // Subscribe to direct messages
    void subscribe_direct(NodeId node_id, std::function<void(Message&)> handler) {
        std::string topic = fmt::format("nodes.{}", node_id);
        subscriptions[topic] = connection.subscribe(topic, handler);
    }

    // Publish state update
    void publish_cell_update(CellId cell, StateUpdateMessage& msg) {
        std::string topic = fmt::format("cells.{}.{}.{}",
            cell.continent_id, cell.x, cell.y);

        connection.publish(topic, serialize(msg));
    }
};
```

## Event Log (Kafka)

### Event Types

```cpp
// All state changes are recorded as events
struct Event {
    EventType type;
    uint64_t timestamp;
    uint64_t sequence;      // Per-partition sequence number
    CellId cell;
    EntityId entity;

    std::vector<uint8_t> payload;
};

enum class EventType {
    // Entity lifecycle
    ENTITY_SPAWN,
    ENTITY_DESPAWN,
    ENTITY_MIGRATE,

    // State changes
    POSITION_CHANGE,
    VITALS_CHANGE,
    COMBAT_START,
    COMBAT_END,
    DAMAGE_DEALT,
    HEALING_DONE,
    SPELL_CAST,
    BUFF_APPLIED,
    BUFF_REMOVED,

    // Inventory
    ITEM_ACQUIRED,
    ITEM_LOST,
    GOLD_CHANGE,

    // Quest
    QUEST_ACCEPTED,
    QUEST_PROGRESS,
    QUEST_COMPLETED,

    // System
    CELL_SPLIT,
    CELL_MERGE,
    NODE_FAILURE,
};
```

### Partitioning Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Kafka Partitioning                                     │
│                                                                              │
│  Topic: events.eastern_kingdoms                                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Partition 0: Cells (0,0) - (15,15)                                  │   │
│  │  ┌────────┬────────┬────────┬────────┬────────┬────────┐            │   │
│  │  │ Event  │ Event  │ Event  │ Event  │ Event  │  ...   │            │   │
│  │  │ seq=1  │ seq=2  │ seq=3  │ seq=4  │ seq=5  │        │            │   │
│  │  └────────┴────────┴────────┴────────┴────────┴────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Partition 1: Cells (16,0) - (31,15)                                 │   │
│  │  ┌────────┬────────┬────────┬────────┬────────┬────────┐            │   │
│  │  │ Event  │ Event  │ Event  │ Event  │ Event  │  ...   │            │   │
│  │  │ seq=1  │ seq=2  │ seq=3  │ seq=4  │ seq=5  │        │            │   │
│  │  └────────┴────────┴────────┴────────┴────────┴────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ...                                                                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Partition 15: Cells (48,48) - (63,63)                               │   │
│  │  ┌────────┬────────┬────────┬────────┬────────┬────────┐            │   │
│  │  │ Event  │ Event  │ Event  │ Event  │ Event  │  ...   │            │   │
│  │  └────────┴────────┴────────┴────────┴────────┴────────┘            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Partition assignment: hash(cell_id) % num_partitions                       │
│  Guarantees: Events for same cell are ordered                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Event Production

```cpp
class EventProducer {
    kafka::Producer producer;

public:
    void emit(const Event& event) {
        std::string topic = fmt::format("events.{}", continent_name(event.cell));

        // Partition by cell for ordering
        int partition = hash(event.cell) % num_partitions;

        producer.produce(topic, partition, serialize(event));
    }

    // Batch emit for efficiency
    void emit_batch(const std::vector<Event>& events) {
        for (const auto& event : events) {
            emit(event);
        }
        producer.flush();  // Ensure all events are sent
    }
};
```

### Event Consumption (for Recovery)

```cpp
class EventConsumer {
    kafka::Consumer consumer;

public:
    // Replay events for a cell from a specific point
    void replay_from(CellId cell, uint64_t from_sequence) {
        std::string topic = fmt::format("events.{}", continent_name(cell));
        int partition = hash(cell) % num_partitions;

        consumer.assign(topic, partition, from_sequence);

        while (true) {
            auto msg = consumer.poll(std::chrono::seconds(1));
            if (!msg) break;

            auto event = deserialize<Event>(msg->payload());
            if (event.cell != cell) continue;  // Skip other cells in partition

            apply_event(event);
        }
    }
};
```

## Cross-Node Interaction Protocol

### Combat Between Entities on Different Nodes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Cross-Node Combat Protocol                                │
│                                                                              │
│   Bot Compute        Zone Node A         Zone Node B         Message Bus    │
│   (Bot Owner)        (Bot Cell)          (Target Cell)                      │
│       │                  │                    │                    │         │
│       │                  │                    │                    │         │
│   ┌───┴───┐              │                    │                    │         │
│   │ AI    │              │                    │                    │         │
│   │decides│              │                    │                    │         │
│   │attack │              │                    │                    │         │
│   └───┬───┘              │                    │                    │         │
│       │                  │                    │                    │         │
│       │  1. ActionRequest (attack target)     │                    │         │
│       │─────────────────►│                    │                    │         │
│       │                  │                    │                    │         │
│       │            ┌─────┴─────┐              │                    │         │
│       │            │ Check if  │              │                    │         │
│       │            │ target is │              │                    │         │
│       │            │ local     │              │                    │         │
│       │            └─────┬─────┘              │                    │         │
│       │                  │                    │                    │         │
│       │                  │  2. CrossCellAttack│                    │         │
│       │                  │───────────────────►│                    │         │
│       │                  │                    │                    │         │
│       │                  │              ┌─────┴─────┐              │         │
│       │                  │              │ Validate: │              │         │
│       │                  │              │ - Range   │              │         │
│       │                  │              │ - LoS     │              │         │
│       │                  │              │ - Cooldowns│             │         │
│       │                  │              │ Calculate │              │         │
│       │                  │              │ damage    │              │         │
│       │                  │              └─────┬─────┘              │         │
│       │                  │                    │                    │         │
│       │                  │  3. AttackResult   │                    │         │
│       │                  │◄───────────────────│                    │         │
│       │                  │                    │                    │         │
│       │  4. ActionResponse                    │                    │         │
│       │◄─────────────────│                    │                    │         │
│       │                  │                    │                    │         │
│       │                  │                    │  5. StateUpdate    │         │
│       │                  │                    │  (health change)   │         │
│       │                  │                    │───────────────────►│         │
│       │                  │                    │                    │         │
│       │                  │                    │  6. Event          │         │
│       │                  │                    │  (damage dealt)    │         │
│       │                  │                    │───────────────────►│ Kafka   │
│       │                  │                    │                    │         │
│                                                                              │
│   Total latency: 10-30ms (same region)                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Message Format for Cross-Node Combat

```cpp
struct CrossCellAttackRequest {
    MessageType type = MessageType::CROSS_CELL_ATTACK;
    uint64_t request_id;

    EntityId attacker;
    EntityId target;
    uint32_t ability_id;

    // Attacker state snapshot (for validation)
    Position attacker_position;
    uint32_t attacker_power;
    uint64_t attacker_tick;
};

struct CrossCellAttackResponse {
    MessageType type = MessageType::CROSS_CELL_ATTACK_RESPONSE;
    uint64_t request_id;

    ResultCode result;
    uint32_t damage_dealt;
    bool target_died;

    // Updated target state
    uint32_t target_health;
    uint32_t target_max_health;
};
```

## Serialization

### Binary Protocol

```cpp
// Efficient binary serialization
class MessageSerializer {
public:
    template<typename T>
    static std::vector<uint8_t> serialize(const T& msg) {
        std::vector<uint8_t> buffer;
        buffer.reserve(sizeof(T) + 64);  // Estimate

        // Header
        write_u8(buffer, static_cast<uint8_t>(T::MESSAGE_TYPE));
        write_u32(buffer, 0);  // Placeholder for size

        // Payload
        serialize_payload(buffer, msg);

        // Update size
        uint32_t size = buffer.size() - 5;
        memcpy(&buffer[1], &size, sizeof(size));

        return buffer;
    }

    template<typename T>
    static T deserialize(const std::vector<uint8_t>& data) {
        size_t offset = 0;

        auto type = read_u8(data, offset);
        auto size = read_u32(data, offset);

        T msg;
        deserialize_payload(data, offset, msg);
        return msg;
    }

private:
    static void serialize_payload(std::vector<uint8_t>& buf, const StateUpdateMessage& msg) {
        write_u16(buf, msg.cell.continent_id);
        write_u8(buf, msg.cell.x);
        write_u8(buf, msg.cell.y);
        write_u64(buf, msg.tick);
        write_u64(buf, msg.timestamp);

        write_u16(buf, msg.updates.size());
        for (const auto& update : msg.updates) {
            serialize_entity_update(buf, update);
        }
    }

    static void serialize_entity_update(std::vector<uint8_t>& buf, const EntityUpdate& u) {
        write_u64(buf, u.entity_id.value);
        write_u8(buf, static_cast<uint8_t>(u.type));

        switch (u.type) {
            case UpdateType::POSITION:
                write_f32(buf, u.position.x);
                write_f32(buf, u.position.y);
                write_f32(buf, u.position.z);
                write_f32(buf, u.position.orientation);
                write_u8(buf, u.position.move_flags);
                break;

            case UpdateType::VITALS:
                write_u32(buf, u.vitals.health);
                write_u32(buf, u.vitals.power);
                write_u8(buf, u.vitals.alive);
                break;

            // ... other types
        }
    }
};
```

## Rate Limiting & Flow Control

### Publisher Rate Limiting

```cpp
class RateLimitedPublisher {
    MessageBusClient& client;
    TokenBucket bucket;

public:
    RateLimitedPublisher(MessageBusClient& c, size_t rate_per_second)
        : client(c), bucket(rate_per_second, rate_per_second) {}

    bool publish(const std::string& topic, const Message& msg) {
        if (!bucket.try_consume(1)) {
            // Rate limited - queue or drop
            return false;
        }
        client.publish(topic, msg);
        return true;
    }
};

class TokenBucket {
    std::atomic<double> tokens;
    double rate;
    double capacity;
    std::chrono::steady_clock::time_point last_refill;

public:
    bool try_consume(double amount) {
        refill();
        double current = tokens.load();
        if (current < amount) return false;
        return tokens.compare_exchange_strong(current, current - amount);
    }

private:
    void refill() {
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration<double>(now - last_refill).count();
        double new_tokens = std::min(capacity, tokens.load() + elapsed * rate);
        tokens.store(new_tokens);
        last_refill = now;
    }
};
```

### Backpressure Handling

```cpp
class BackpressureHandler {
    std::atomic<size_t> pending_messages{0};
    const size_t max_pending = 10000;

public:
    bool can_send() const {
        return pending_messages.load() < max_pending;
    }

    void on_send() {
        pending_messages.fetch_add(1);
    }

    void on_ack() {
        pending_messages.fetch_sub(1);
    }

    // Adaptive behavior when backpressured
    void handle_backpressure() {
        // Options:
        // 1. Reduce update frequency
        // 2. Aggregate updates (batch position changes)
        // 3. Drop low-priority updates
        // 4. Spill to disk
    }
};
```

## Configuration

```yaml
# messaging.yaml
nats:
  servers:
    - nats://nats-1:4222
    - nats://nats-2:4222
    - nats://nats-3:4222
  max_reconnects: 10
  reconnect_wait_ms: 1000

  publish:
    max_pending: 10000
    rate_limit_per_topic: 10000  # messages/second

  subscribe:
    buffer_size: 65536
    pending_message_limit: 100000

kafka:
  brokers:
    - kafka-1:9092
    - kafka-2:9092
    - kafka-3:9092

  producer:
    batch_size: 16384
    linger_ms: 5
    compression: lz4
    acks: 1  # Leader ack only for speed

  consumer:
    fetch_min_bytes: 1024
    fetch_max_wait_ms: 100
    auto_offset_reset: earliest

  topics:
    events:
      partitions: 16
      replication_factor: 3
      retention_hours: 168  # 7 days
```

## Next Steps

- [06-consistency.md](06-consistency.md) - How consistency is maintained
- [07-failure-handling.md](07-failure-handling.md) - What happens when messages fail
