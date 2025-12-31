# Implementation Roadmap

This document outlines a phased approach to building Swarm, starting from the current mod-playerbots codebase and incrementally evolving toward the full distributed architecture.

## Phase Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Implementation Phases                                 │
│                                                                              │
│  Phase 1          Phase 2           Phase 3           Phase 4              │
│  ────────         ────────          ────────          ────────             │
│  ECS Refactor     Multi-Process     Distributed       Full Scale           │
│                                     Coordination                            │
│                                                                              │
│  ┌─────────┐     ┌─────────┐       ┌─────────┐       ┌─────────┐          │
│  │ Single  │     │ Single  │       │ Multi   │       │ Multi   │          │
│  │ Process │ ──► │ Machine │ ───►  │ Machine │ ───►  │ Region  │          │
│  │ 2-5K    │     │ 50K     │       │ 500K    │       │ 10M+    │          │
│  │ bots    │     │ bots    │       │ bots    │       │ bots    │          │
│  └─────────┘     └─────────┘       └─────────┘       └─────────┘          │
│                                                                              │
│  Duration:        Duration:         Duration:         Duration:            │
│  3-4 months       2-3 months        4-6 months        3-4 months           │
│                                                                              │
│  Risk: Medium     Risk: Medium      Risk: High        Risk: Medium         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Phase 1: ECS Refactor (Single Process)

**Goal**: Refactor bot representation to Entity Component System while staying single-process.

**Duration**: 3-4 months

**Bot Capacity**: 2,000 → 5,000 bots

### Deliverables

1. **Component-based bot representation**
2. **Data-oriented memory layout**
3. **Batch processing for AI updates**
4. **Baseline performance benchmarks**

### Tasks

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 1 Tasks                                                               │
│                                                                              │
│  1.1 Core ECS Framework                                                      │
│  ├── Define component structs (Position, Vitals, Combat, AI)                │
│  ├── Implement entity registry (ID allocation, component storage)           │
│  ├── Create component iterators (for batch processing)                      │
│  └── Unit tests for ECS primitives                                          │
│                                                                              │
│  1.2 Bot Migration to ECS                                                    │
│  ├── Create adapter layer (ECS ↔ existing PlayerbotAI)                      │
│  ├── Migrate bot state to components incrementally                          │
│  ├── Update AI to use component queries                                      │
│  └── Remove deprecated bot data structures                                   │
│                                                                              │
│  1.3 Batch AI Processing                                                     │
│  ├── Group bots by behavior state                                            │
│  ├── Process similar bots together (cache efficiency)                       │
│  ├── Parallelize independent operations                                      │
│  └── Benchmark: 5Hz update for 5,000 bots                                   │
│                                                                              │
│  1.4 Memory Optimization                                                     │
│  ├── Separate hot/cold component data                                        │
│  ├── Implement object pools for actions                                      │
│  ├── Reduce per-bot memory to <1KB core state                               │
│  └── Profile and eliminate allocations in hot paths                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Code Example: ECS Migration

```cpp
// Before: Traditional OOP
class PlayerbotAI {
    Player* bot;
    BotState state;
    ThreatManager threatManager;
    MovementGenerator movementGen;
    // ... 100+ members
};

// After: ECS Components
struct BotEntity {
    EntityId id;
    // Components stored separately in contiguous arrays
};

struct PositionComponent { float x, y, z, orientation; };
struct VitalsComponent { uint32_t health, power; };
struct AIStateComponent { uint8_t behavior_state; EntityId target; };
struct CombatComponent { ThreatList threats; uint32_t swing_timer; };

class BotWorld {
    ComponentArray<PositionComponent> positions;
    ComponentArray<VitalsComponent> vitals;
    ComponentArray<AIStateComponent> ai_states;
    ComponentArray<CombatComponent> combat;

    void update_ai() {
        // Batch process all idle bots
        for (auto& [id, ai] : ai_states.where(is_idle)) {
            update_idle_bot(id, ai, positions[id]);
        }

        // Batch process all combat bots
        for (auto& [id, ai] : ai_states.where(is_in_combat)) {
            update_combat_bot(id, ai, combat[id], positions[id]);
        }
    }
};
```

### Success Criteria

- [ ] 5,000 bots at 5Hz update rate
- [ ] <50ms tick time for AI updates
- [ ] <500 bytes per bot core memory
- [ ] All existing bot behaviors preserved

---

## Phase 2: Multi-Process Architecture (Single Machine)

**Goal**: Separate bot AI into a dedicated process, communicating with worldserver via IPC.

**Duration**: 2-3 months

**Bot Capacity**: 5,000 → 50,000 bots

### Deliverables

1. **Separate bot-engine process**
2. **Shared memory communication**
3. **World view synchronization**
4. **Action dispatch and validation**

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Phase 2 Architecture                                     │
│                                                                              │
│  ┌─────────────────────────────┐     ┌─────────────────────────────┐       │
│  │       World Server          │     │       Bot Engine            │       │
│  │                             │     │                             │       │
│  │  ┌─────────────────────┐   │     │   ┌─────────────────────┐   │       │
│  │  │  Player Management  │   │     │   │   AI Processing     │   │       │
│  │  │  Combat System      │   │     │   │   Pathfinding       │   │       │
│  │  │  Spell System       │   │     │   │   Behavior Trees    │   │       │
│  │  │  World State        │   │     │   │   World View Cache  │   │       │
│  │  └─────────────────────┘   │     │   └─────────────────────┘   │       │
│  │            │               │     │             │               │       │
│  │            ▼               │     │             ▼               │       │
│  │  ┌─────────────────────┐   │     │   ┌─────────────────────┐   │       │
│  │  │  IPC: State Export  │◄──┼─────┼──►│  IPC: State Import  │   │       │
│  │  │  IPC: Action Import │   │ SHM │   │  IPC: Action Export │   │       │
│  │  └─────────────────────┘   │     │   └─────────────────────┘   │       │
│  │                             │     │                             │       │
│  └─────────────────────────────┘     └─────────────────────────────┘       │
│                                                                              │
│  Communication: Shared Memory (mmap) + Signals                              │
│  Latency: < 1ms                                                             │
│  Throughput: 1M+ updates/second                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tasks

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 2 Tasks                                                               │
│                                                                              │
│  2.1 IPC Framework                                                           │
│  ├── Design shared memory layout (ring buffers)                             │
│  ├── Implement lock-free message passing                                     │
│  ├── Create serialization for entity state                                   │
│  └── Benchmark: 1M messages/second                                          │
│                                                                              │
│  2.2 Bot Engine Process                                                      │
│  ├── Create standalone bot-engine executable                                │
│  ├── Import ECS and AI code from Phase 1                                    │
│  ├── Implement world view synchronization                                    │
│  └── Add process lifecycle management                                        │
│                                                                              │
│  2.3 World Server Integration                                                │
│  ├── Export entity state to shared memory                                    │
│  ├── Import and validate bot actions                                         │
│  ├── Handle bot engine crash/restart                                         │
│  └── Metrics and logging for IPC                                            │
│                                                                              │
│  2.4 Hierarchical AI                                                         │
│  ├── Implement squad system (leader + members)                              │
│  ├── Simplified follower AI (execute commands)                              │
│  ├── Leader AI with full decision making                                    │
│  └── Benchmark: 80% reduction in AI compute                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Code Example: Shared Memory IPC

```cpp
// Shared memory layout
struct SharedBotState {
    // Lock-free ring buffer for world updates
    struct UpdateRing {
        std::atomic<uint64_t> write_pos;
        std::atomic<uint64_t> read_pos;
        EntityUpdate updates[RING_SIZE];
    } world_updates;

    // Lock-free ring buffer for bot actions
    struct ActionRing {
        std::atomic<uint64_t> write_pos;
        std::atomic<uint64_t> read_pos;
        BotAction actions[RING_SIZE];
    } bot_actions;

    // Snapshot of nearby entities (updated periodically)
    EntitySnapshot entities[MAX_ENTITIES];
    std::atomic<uint32_t> entity_count;
};

// In worldserver
void export_state_to_bot_engine() {
    auto* shared = get_shared_memory<SharedBotState>();

    for (const auto& entity : visible_entities) {
        EntityUpdate update{entity.id, entity.position, entity.health};
        shared->world_updates.push(update);
    }
}

// In bot-engine
void import_state_from_worldserver() {
    auto* shared = get_shared_memory<SharedBotState>();

    while (auto update = shared->world_updates.pop()) {
        world_cache.apply(*update);
    }
}
```

### Success Criteria

- [ ] 50,000 bots at 5Hz update rate
- [ ] Bot engine restart without worldserver impact
- [ ] <5ms round-trip IPC latency
- [ ] CPU distributed across multiple cores

---

## Phase 3: Distributed Coordination (Multi-Machine)

**Goal**: Deploy across multiple machines with cell-based sharding and message bus.

**Duration**: 4-6 months

**Bot Capacity**: 50,000 → 500,000 bots

### Deliverables

1. **Cell-based spatial sharding**
2. **NATS message bus integration**
3. **Kafka event log**
4. **Coordinator service**
5. **Entity migration protocol**

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     Phase 3 Architecture                                     │
│                                                                              │
│                        ┌─────────────────┐                                  │
│                        │   Coordinator   │                                  │
│                        │    Cluster      │                                  │
│                        └────────┬────────┘                                  │
│                                 │                                            │
│              ┌──────────────────┼──────────────────┐                        │
│              │                  │                  │                        │
│              ▼                  ▼                  ▼                        │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐         │
│  │   Zone Node 1     │ │   Zone Node 2     │ │   Zone Node 3     │         │
│  │   (Cells A, B)    │ │   (Cells C, D)    │ │   (Cells E, F)    │         │
│  └─────────┬─────────┘ └─────────┬─────────┘ └─────────┬─────────┘         │
│            │                     │                     │                    │
│            └─────────────────────┼─────────────────────┘                    │
│                                  │                                          │
│                        ┌─────────▼─────────┐                                │
│                        │    NATS Cluster   │                                │
│                        └─────────┬─────────┘                                │
│                                  │                                          │
│            ┌─────────────────────┼─────────────────────┐                    │
│            │                     │                     │                    │
│            ▼                     ▼                     ▼                    │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐         │
│  │ Bot Compute 1     │ │ Bot Compute 2     │ │ Bot Compute 3     │         │
│  │ (50K bots)        │ │ (50K bots)        │ │ (50K bots)        │         │
│  └───────────────────┘ └───────────────────┘ └───────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tasks

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 3 Tasks                                                               │
│                                                                              │
│  3.1 Cell-Based Sharding                                                     │
│  ├── Define cell structure and boundaries                                   │
│  ├── Implement cell assignment to Zone Nodes                                │
│  ├── Create boundary entity handling                                         │
│  └── Test with 2 Zone Nodes                                                  │
│                                                                              │
│  3.2 Message Bus Integration                                                 │
│  ├── Deploy NATS cluster                                                     │
│  ├── Implement pub/sub for state updates                                    │
│  ├── Implement request/reply for actions                                    │
│  └── Add message serialization (protobuf or flatbuffers)                   │
│                                                                              │
│  3.3 Event Sourcing                                                          │
│  ├── Deploy Kafka cluster                                                    │
│  ├── Publish all state changes as events                                    │
│  ├── Implement event replay for recovery                                    │
│  └── Create periodic state checkpoints                                       │
│                                                                              │
│  3.4 Coordinator Service                                                     │
│  ├── Implement cell assignment logic                                         │
│  ├── Add health monitoring for nodes                                         │
│  ├── Create failure detection and recovery                                   │
│  └── Build admin API for cluster management                                 │
│                                                                              │
│  3.5 Entity Migration                                                        │
│  ├── Implement migration protocol                                            │
│  ├── Handle cross-node combat                                                │
│  ├── Test with high-traffic migrations                                       │
│  └── Benchmark migration latency (<50ms)                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Success Criteria

- [ ] 500,000 bots across 10 Zone Nodes
- [ ] <50ms entity migration latency
- [ ] Recovery from node failure in <30 seconds
- [ ] Linear scaling verified (add node = add capacity)

---

## Phase 4: Full Horizontal Scale (Multi-Region)

**Goal**: Production-ready deployment with multi-region support and full automation.

**Duration**: 3-4 months

**Bot Capacity**: 500,000 → 10,000,000+ bots

### Deliverables

1. **Kubernetes deployment**
2. **Auto-scaling**
3. **Multi-region support**
4. **Observability stack**
5. **Disaster recovery**

### Tasks

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 4 Tasks                                                               │
│                                                                              │
│  4.1 Kubernetes Deployment                                                   │
│  ├── Create Helm charts for all components                                  │
│  ├── Configure StatefulSets for Zone Nodes                                  │
│  ├── Configure Deployments for Bot Compute                                  │
│  └── Set up PodDisruptionBudgets and resource limits                       │
│                                                                              │
│  4.2 Auto-Scaling                                                            │
│  ├── Implement HPA for Bot Compute Nodes                                    │
│  ├── Create custom metrics adapter for cell load                            │
│  ├── Add predictive scaling based on historical patterns                   │
│  └── Test scale-up/down under load                                          │
│                                                                              │
│  4.3 Multi-Region                                                            │
│  ├── Deploy to 2+ cloud regions                                              │
│  ├── Configure cross-region Kafka replication                               │
│  ├── Implement region-aware cell assignment                                  │
│  └── Test failover between regions                                          │
│                                                                              │
│  4.4 Observability                                                           │
│  ├── Deploy Prometheus + Grafana                                            │
│  ├── Add distributed tracing (Jaeger)                                       │
│  ├── Create alerting rules                                                   │
│  └── Build operational dashboards                                            │
│                                                                              │
│  4.5 Disaster Recovery                                                       │
│  ├── Implement automated backups                                             │
│  ├── Test restore from backup                                                │
│  ├── Create runbooks for failure scenarios                                  │
│  └── Conduct chaos engineering tests                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Success Criteria

- [ ] 10,000,000+ bots capacity
- [ ] 99.9% availability
- [ ] <5 minute recovery from region failure
- [ ] Fully automated deployment and scaling

---

## Risk Mitigation

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| ECS migration breaks existing behaviors | Medium | High | Extensive testing, gradual rollout |
| IPC performance insufficient | Low | High | Prototype early, have fallback to threads |
| Message bus becomes bottleneck | Medium | Medium | Design for partitioning, test at scale |
| Consistency bugs in distributed state | High | High | Formal verification, extensive testing |
| Migration protocol edge cases | High | Medium | Comprehensive integration tests |

### Rollback Strategy

Each phase maintains backward compatibility:

- **Phase 1**: Can revert to pre-ECS code
- **Phase 2**: Bot engine crash falls back to in-process bots
- **Phase 3**: Single-node mode still works
- **Phase 4**: Can run without Kubernetes

---

## Resource Requirements

### Team Composition

| Role | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| Systems Engineer | 2 | 2 | 3 | 2 |
| Backend Developer | 1 | 2 | 3 | 2 |
| DevOps/SRE | 0 | 1 | 2 | 3 |
| QA Engineer | 1 | 1 | 2 | 2 |

### Infrastructure (Development)

| Component | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|-----------|---------|---------|---------|---------|
| Dev Machines | 2 | 4 | 8 | 8 |
| Test Cluster | 0 | 0 | 5 nodes | 20 nodes |
| CI/CD | Basic | Basic | Full | Full |

---

## Timeline Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Project Timeline                                    │
│                                                                              │
│  Month:  1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16     │
│          │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │     │
│  Phase 1 ████████████████                                                    │
│  (ECS)   └── 5K bots ──┘                                                    │
│                                                                              │
│  Phase 2             ████████████                                            │
│  (Multi-Process)     └─ 50K bots ┘                                          │
│                                                                              │
│  Phase 3                         ████████████████████████                   │
│  (Distributed)                   └──── 500K bots ────────┘                  │
│                                                                              │
│  Phase 4                                                 ████████████████   │
│  (Full Scale)                                            └── 10M+ bots ──┘  │
│                                                                              │
│  Key Milestones:                                                            │
│  ★ Month 4:  ECS complete, 5K bots working                                  │
│  ★ Month 7:  Multi-process working, 50K bots                               │
│  ★ Month 13: Distributed cluster, 500K bots                                │
│  ★ Month 16: Production ready, 10M+ bots                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Getting Started

To begin Phase 1:

1. **Read** [03-entity-management.md](03-entity-management.md) for ECS design
2. **Create** a new branch: `feature/ecs-refactor`
3. **Implement** the component structs in `src/ecs/components.h`
4. **Write tests** for the entity registry
5. **Migrate** one simple bot behavior as a proof of concept

## Conclusion

This roadmap provides a path from the current ~500 bot limit to 10M+ bots through incremental, testable phases. Each phase delivers value and can be deployed independently, reducing risk while building toward the full vision.

The key insight is that **most of the complexity is in Phase 3** (distributed coordination). Phases 1 and 2 build the foundation and can be completed with a small team, while Phase 3 requires careful design and extensive testing.
