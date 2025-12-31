# System Overview

This document describes the high-level architecture of the Swarm distributed bot system.

## Architecture Layers

The system is organized into four distinct layers, each with specific responsibilities:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         GLOBAL LAYER                                    │ │
│  │                                                                         │ │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│  │   │   Config    │  │   Service   │  │   Global    │  │  Metrics &  │  │ │
│  │   │   Store     │  │  Discovery  │  │   Clock     │  │  Telemetry  │  │ │
│  │   │   (etcd)    │  │  (Consul)   │  │  (Hybrid)   │  │(Prometheus) │  │ │
│  │   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                       COORDINATION LAYER                                │ │
│  │                                                                         │ │
│  │   ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │   │                  World Coordinator Cluster                       │  │ │
│  │   │                                                                   │  │ │
│  │   │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │  │ │
│  │   │  │   Shard   │  │  Entity   │  │   Load    │  │ Migration │    │  │ │
│  │   │  │  Manager  │  │ Registry  │  │ Balancer  │  │ Scheduler │    │  │ │
│  │   │  └───────────┘  └───────────┘  └───────────┘  └───────────┘    │  │ │
│  │   │                                                                   │  │ │
│  │   └─────────────────────────────────────────────────────────────────┘  │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                    ┌─────────────────┼─────────────────┐                    │
│                    ▼                 ▼                 ▼                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                          COMPUTE LAYER                                  │ │
│  │                                                                         │ │
│  │   ┌─────────────────────────┐      ┌─────────────────────────┐        │ │
│  │   │      Zone Nodes         │      │    Bot Compute Nodes    │        │ │
│  │   │                         │      │                         │        │ │
│  │   │  ┌───────┐  ┌───────┐  │      │  ┌───────┐  ┌───────┐  │        │ │
│  │   │  │ Cell  │  │ Cell  │  │      │  │  AI   │  │  AI   │  │        │ │
│  │   │  │Manager│  │Manager│  │      │  │Engine │  │Engine │  │        │ │
│  │   │  └───────┘  └───────┘  │      │  └───────┘  └───────┘  │        │ │
│  │   │                         │      │                         │        │ │
│  │   │  World Simulation       │      │  Decision Processing    │        │ │
│  │   │  Physics, Combat        │      │  Pathfinding, Tactics   │        │ │
│  │   │  State Authority        │      │  Behavior Trees         │        │ │
│  │   └─────────────────────────┘      └─────────────────────────┘        │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                       │
│                                      ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                           DATA LAYER                                    │ │
│  │                                                                         │ │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│  │   │  Event Log  │  │   State     │  │    Blob     │  │  Message    │  │ │
│  │   │  (Kafka)    │  │   Store     │  │   Store     │  │    Bus      │  │ │
│  │   │             │  │ (ScyllaDB)  │  │  (S3/MinIO) │  │   (NATS)    │  │ │
│  │   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Layer Responsibilities

### Global Layer

The Global Layer provides cluster-wide services that all other components depend on.

| Component | Responsibility | Technology |
|-----------|---------------|------------|
| **Config Store** | Cluster configuration, feature flags, cell assignments | etcd |
| **Service Discovery** | Node registration, health checks, endpoint resolution | Consul |
| **Global Clock** | Hybrid logical clocks for event ordering | Custom + NTP |
| **Metrics & Telemetry** | Performance monitoring, alerting, tracing | Prometheus + Jaeger |

**Availability Requirements**: 99.999% (this layer must never go down)

### Coordination Layer

The Coordination Layer manages the distributed state of the world and orchestrates compute resources.

| Component | Responsibility |
|-----------|---------------|
| **Shard Manager** | Assigns cells to Zone Nodes, handles rebalancing |
| **Entity Registry** | Tracks entity locations across the cluster (DHT) |
| **Load Balancer** | Monitors node load, triggers cell migrations |
| **Migration Scheduler** | Coordinates entity transfers between nodes |

**Scaling**: 3-5 coordinator nodes (Raft consensus), handles up to 1000 Zone Nodes

### Compute Layer

The Compute Layer performs the actual simulation and AI processing.

#### Zone Nodes (World Simulation)
- Own a set of spatial cells
- Authoritative for entities within their cells
- Process combat, physics, spell effects
- Handle entity migration at cell boundaries
- Publish state updates to subscribers

**Capacity**: ~100,000-500,000 entities per node

#### Bot Compute Nodes (AI Processing)
- Subscribe to world state from Zone Nodes
- Run AI decision-making for assigned bots
- Send action requests to Zone Nodes
- Maintain local world view cache
- Implement hierarchical AI (squad-based)

**Capacity**: ~50,000-100,000 bots per node

### Data Layer

The Data Layer provides persistence and inter-node communication.

| Component | Purpose | Characteristics |
|-----------|---------|-----------------|
| **Event Log** | Durable event stream, replay capability | Append-only, partitioned by cell |
| **State Store** | Entity state persistence, checkpoints | Low-latency reads, high write throughput |
| **Blob Store** | Large assets, snapshots | Cold storage, infrequent access |
| **Message Bus** | Real-time inter-node communication | Sub-millisecond latency, pub/sub |

## Technology Stack

### Compute Technologies

| Technology | Usage | Justification |
|------------|-------|---------------|
| **Rust** | Zone Nodes, Bot Compute | Zero-cost abstractions, no GC pauses, memory safety |
| **C++** | Performance-critical paths | Integration with existing game code |
| **Go** | Coordination services | Fast development, good concurrency |

### Data Technologies

| Technology | Usage | Justification |
|------------|-------|---------------|
| **Apache Kafka** | Event log | Proven durability, horizontal scaling, exactly-once semantics |
| **ScyllaDB** | State store | Low-latency, C++ implementation, Cassandra-compatible |
| **Redis** | Caching, ephemeral state | Sub-millisecond latency, data structures |
| **NATS** | Message bus | Lightweight, high throughput, clustering |
| **MinIO/S3** | Blob storage | Standard interface, cost-effective |

### Infrastructure Technologies

| Technology | Usage | Justification |
|------------|-------|---------------|
| **Kubernetes** | Container orchestration | Auto-scaling, self-healing, standard |
| **etcd** | Configuration store | Raft consensus, proven reliability |
| **Consul** | Service discovery | Health checks, multi-datacenter |
| **Prometheus** | Metrics | De facto standard, powerful queries |
| **Jaeger** | Distributed tracing | OpenTelemetry compatible |

## Deployment Topology

### Single-Region Deployment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Region: US-East                                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      Availability Zone A                                │ │
│  │                                                                         │ │
│  │   Coordinator    Zone Nodes       Bot Compute      Kafka Brokers       │ │
│  │   ┌───┐         ┌───┬───┬───┐   ┌───┬───┬───┐    ┌───┬───┐           │ │
│  │   │ C │         │ Z │ Z │ Z │   │ B │ B │ B │    │ K │ K │           │ │
│  │   └───┘         └───┴───┴───┘   └───┴───┴───┘    └───┴───┘           │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      Availability Zone B                                │ │
│  │                                                                         │ │
│  │   Coordinator    Zone Nodes       Bot Compute      Kafka Brokers       │ │
│  │   ┌───┐         ┌───┬───┬───┐   ┌───┬───┬───┐    ┌───┬───┐           │ │
│  │   │ C │         │ Z │ Z │ Z │   │ B │ B │ B │    │ K │ K │           │ │
│  │   └───┘         └───┴───┴───┘   └───┴───┴───┘    └───┴───┘           │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      Availability Zone C                                │ │
│  │                                                                         │ │
│  │   Coordinator    Zone Nodes       Bot Compute      Kafka Brokers       │ │
│  │   ┌───┐         ┌───┬───┬───┐   ┌───┬───┬───┐    ┌───┬───┐           │ │
│  │   │ C │         │ Z │ Z │ Z │   │ B │ B │ B │    │ K │ K │           │ │
│  │   └───┘         └───┴───┴───┘   └───┴───┴───┘    └───┴───┘           │ │
│  │                                                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ScyllaDB Cluster (3+ nodes)    Redis Cluster    etcd Cluster (3 nodes)    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Multi-Region Deployment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Global Coordination                                 │
│                                                                              │
│   ┌─────────────┐              ┌─────────────┐              ┌─────────────┐ │
│   │  US-East    │◄────────────►│  EU-West    │◄────────────►│ Asia-Pacific│ │
│   │             │   Cross-DC   │             │   Cross-DC   │             │ │
│   │  Primary    │   Replication│  Secondary  │   Replication│  Secondary  │ │
│   └─────────────┘              └─────────────┘              └─────────────┘ │
│         │                            │                            │         │
│         ▼                            ▼                            ▼         │
│   ┌─────────────┐              ┌─────────────┐              ┌─────────────┐ │
│   │ Zone Nodes  │              │ Zone Nodes  │              │ Zone Nodes  │ │
│   │ Bot Compute │              │ Bot Compute │              │ Bot Compute │ │
│   │ (Eastern    │              │ (Kalimdor   │              │ (Outland    │ │
│   │  Kingdoms)  │              │  Northrend) │              │  Instances) │ │
│   └─────────────┘              └─────────────┘              └─────────────┘ │
│                                                                              │
│   Inter-region latency: 50-150ms (acceptable for cross-continent travel)   │
│   Intra-region latency: < 5ms (required for combat)                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Normal Operation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Normal Operation Data Flow                            │
│                                                                              │
│   Bot Compute Node                Zone Node                   Other Nodes   │
│         │                             │                            │         │
│         │  1. World State Updates     │                            │         │
│         │◄────────────────────────────│                            │         │
│         │    (positions, health,      │                            │         │
│         │     nearby entities)        │                            │         │
│         │                             │                            │         │
│   ┌─────▼─────┐                       │                            │         │
│   │ AI Engine │                       │                            │         │
│   │ Decisions │                       │                            │         │
│   └─────┬─────┘                       │                            │         │
│         │                             │                            │         │
│         │  2. Action Request          │                            │         │
│         │────────────────────────────►│                            │         │
│         │    (attack, move, cast)     │                            │         │
│         │                             │                            │         │
│         │                       ┌─────▼─────┐                      │         │
│         │                       │ Validate  │                      │         │
│         │                       │ & Execute │                      │         │
│         │                       └─────┬─────┘                      │         │
│         │                             │                            │         │
│         │                             │  3. State Change Event     │         │
│         │                             │───────────────────────────►│         │
│         │                             │    (damage, death, loot)   │         │
│         │                             │                            │         │
│         │                             │  4. Publish to Kafka       │         │
│         │                             │───────────────────────────►│ Event   │
│         │                             │    (persistent log)        │ Log     │
│         │                             │                            │         │
│         │  5. Action Result           │                            │         │
│         │◄────────────────────────────│                            │         │
│         │    (success/failure)        │                            │         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cross-Node Interaction

See [05-communication.md](05-communication.md) for detailed cross-node protocols.

## Capacity Planning Summary

| Cluster Size | Zone Nodes | Bot Nodes | Total Bots | Events/sec | Cost/month |
|-------------|------------|-----------|------------|------------|------------|
| Dev | 1 | 2 | 50,000 | 100,000 | $500 |
| Small | 5 | 10 | 500,000 | 1,000,000 | $5,000 |
| Medium | 20 | 40 | 2,000,000 | 4,000,000 | $20,000 |
| Large | 50 | 100 | 5,000,000 | 10,000,000 | $50,000 |
| Enterprise | 100 | 200 | 10,000,000 | 20,000,000 | $100,000 |

## Next Steps

- [02-spatial-sharding.md](02-spatial-sharding.md) - How the world is partitioned
- [03-entity-management.md](03-entity-management.md) - Entity state and lifecycle
- [04-bot-compute.md](04-bot-compute.md) - AI architecture details
