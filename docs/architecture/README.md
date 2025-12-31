# Swarm: Distributed Bot Architecture

> A scalable, fault-tolerant architecture for running millions of game bots across distributed infrastructure.

## Executive Summary

This document describes **Swarm**, a next-generation architecture for massively parallel bot simulation. The current mod-playerbots implementation supports approximately 500 bots on a single server. Swarm is designed to scale linearly to **10+ million bots** across distributed infrastructure while maintaining sub-50ms interaction latency.

## Design Goals

| Goal | Target | Rationale |
|------|--------|-----------|
| **Horizontal Scaling** | Linear to 100+ nodes | Add capacity by adding machines |
| **Bot Capacity** | 10,000,000+ | Full world population simulation |
| **Interaction Latency** | < 50ms same-region | Imperceptible to gameplay |
| **Availability** | 99.99% | Automatic failover and recovery |
| **Operational Simplicity** | Kubernetes-native | Standard cloud-native tooling |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GLOBAL LAYER                                       │
│     Config Store (etcd) │ Service Discovery │ Global Clock │ Metrics        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COORDINATION LAYER                                   │
│              World Coordinator Cluster (Shard Manager, Load Balancer)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          COMPUTE LAYER                                       │
│         Zone Nodes (World Sim)  │  Bot Compute Nodes (AI Processing)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA LAYER                                         │
│         Event Log (Kafka) │ State Store (ScyllaDB) │ Message Bus (NATS)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Innovations

### 1. Spatial Sharding
The game world is divided into dynamic cells that are distributed across Zone Nodes. Hot spots (cities, raids) automatically split into smaller cells for load distribution.

### 2. Separated AI Compute
Bot AI processing runs on dedicated nodes, separate from world simulation. This allows independent scaling of "thinking" capacity vs "simulation" capacity.

### 3. Event Sourcing
All state changes are recorded as immutable events. This enables replay, debugging, and recovery from failures by replaying the event log.

### 4. Hierarchical AI
Instead of each bot running full AI, squad leaders make decisions and issue commands to group members. This reduces AI computation by ~80%.

### 5. Eventual Consistency with CRDTs
Non-critical state (positions, health) uses eventual consistency with Conflict-free Replicated Data Types (CRDTs) for high performance. Critical state (inventory, gold) uses strong consistency.

## Documentation Index

| Document | Description |
|----------|-------------|
| [01-system-overview.md](01-system-overview.md) | High-level architecture and component responsibilities |
| [02-spatial-sharding.md](02-spatial-sharding.md) | World partitioning and cell management |
| [03-entity-management.md](03-entity-management.md) | Entity lifecycle and state representation |
| [04-bot-compute.md](04-bot-compute.md) | Bot AI architecture and hierarchical decision making |
| [05-communication.md](05-communication.md) | Inter-node messaging and event sourcing |
| [06-consistency.md](06-consistency.md) | Distributed consistency models and CRDTs |
| [07-failure-handling.md](07-failure-handling.md) | Fault tolerance and recovery procedures |
| [08-scaling.md](08-scaling.md) | Capacity planning and cost modeling |
| [09-implementation-roadmap.md](09-implementation-roadmap.md) | Phased implementation approach |

## Quick Reference: Capacity Estimates

| Configuration | Zone Nodes | Bot Nodes | Max Bots | Monthly Cost |
|--------------|------------|-----------|----------|--------------|
| Small | 5 | 10 | 500,000 | ~$5,000 |
| Medium | 20 | 40 | 2,000,000 | ~$20,000 |
| Large | 50 | 100 | 5,000,000 | ~$50,000 |
| Enterprise | 100 | 200 | 10,000,000 | ~$100,000 |

## Technology Stack

| Component | Technology | Justification |
|-----------|-----------|---------------|
| Compute | Rust / C++ | Zero-cost abstractions, predictable latency |
| Coordination | etcd + Consul | Battle-tested distributed consensus |
| Messaging | NATS | Low-latency pub/sub, millions msgs/sec |
| Event Log | Apache Kafka | Durable, partitioned, replayable events |
| State Store | ScyllaDB | Low-latency, horizontally scalable |
| Orchestration | Kubernetes | Auto-scaling, self-healing |
| Networking | gRPC + QUIC | Efficient binary protocol |

## Current vs Target State

| Metric | Current (mod-playerbots) | Target (Swarm) | Improvement |
|--------|--------------------------|----------------|-------------|
| Max Bots | ~500 | 10,000,000+ | 20,000x |
| CPU Efficiency | Single-threaded | Fully parallel | 100x |
| Memory per Bot | ~100KB | ~8KB | 12x |
| Failure Recovery | Manual restart | Automatic (30s) | N/A |
| Horizontal Scaling | None | Linear | Unlimited |

## Getting Started

For contributors looking to understand or implement this architecture:

1. Start with [01-system-overview.md](01-system-overview.md) for the full picture
2. Review [03-entity-management.md](03-entity-management.md) for the core data model
3. See [09-implementation-roadmap.md](09-implementation-roadmap.md) for the phased approach

## License

This architecture documentation is part of mod-playerbots, released under GNU AGPL v3.
