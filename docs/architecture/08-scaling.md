# Scaling and Capacity Planning

This document provides detailed capacity estimates, cost modeling, and scaling guidelines for Swarm deployments.

## Capacity Model

### Per-Node Capacity

#### Zone Node (World Simulation)

| Resource | Specification | Capacity Impact |
|----------|--------------|-----------------|
| CPU | 32 cores @ 3.0 GHz | ~200,000 entities |
| Memory | 64 GB | ~500,000 entities (128 bytes/entity core state) |
| Network | 10 Gbps | ~1M state updates/second |
| Storage | NVMe SSD | Checkpoint I/O |

**Limiting Factor**: CPU for combat-heavy cells, Memory for high-density cells

#### Bot Compute Node (AI Processing)

| Resource | Specification | Capacity Impact |
|----------|--------------|-----------------|
| CPU | 32 cores @ 3.0 GHz | ~80,000 bots |
| Memory | 32 GB | ~100,000 bots (world view cache) |
| Network | 10 Gbps | ~500K decisions/second |

**Limiting Factor**: CPU (AI processing is compute-bound)

### Workload Profiles

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Workload Profiles                                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Idle World (Bots following players, minimal combat)                 │   │
│  │                                                                       │   │
│  │  CPU per bot: 10 μs/tick                                             │   │
│  │  Memory per bot: 200 bytes                                           │   │
│  │  Events per bot: 5/second                                            │   │
│  │                                                                       │   │
│  │  32-core Zone Node: 400,000 entities                                 │   │
│  │  32-core Bot Compute: 150,000 bots                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Active Combat (Dungeons, open world PvP)                            │   │
│  │                                                                       │   │
│  │  CPU per bot: 50 μs/tick                                             │   │
│  │  Memory per bot: 1 KB (threat tables, auras)                         │   │
│  │  Events per bot: 50/second                                           │   │
│  │                                                                       │   │
│  │  32-core Zone Node: 100,000 entities                                 │   │
│  │  32-core Bot Compute: 60,000 bots                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Raid Combat (40-man raids, complex mechanics)                       │   │
│  │                                                                       │   │
│  │  CPU per bot: 100 μs/tick                                            │   │
│  │  Memory per bot: 2 KB                                                │   │
│  │  Events per bot: 100/second                                          │   │
│  │                                                                       │   │
│  │  32-core Zone Node: 50,000 entities                                  │   │
│  │  32-core Bot Compute: 30,000 bots                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Cluster Sizing

### Reference Configurations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Cluster Configurations                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  DEVELOPMENT (Testing, Development)                                   │   │
│  │                                                                       │   │
│  │  Zone Nodes:        1 (16 cores, 32GB)                               │   │
│  │  Bot Compute Nodes: 1 (16 cores, 16GB)                               │   │
│  │  Coordinator:       1 (embedded)                                      │   │
│  │  Kafka:             1 broker (embedded)                               │   │
│  │  ScyllaDB:          1 node                                            │   │
│  │                                                                       │   │
│  │  Max Bots:          10,000                                            │   │
│  │  Monthly Cost:      ~$200 (cloud) / $0 (local)                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  SMALL (Single Server, Hobby)                                         │   │
│  │                                                                       │   │
│  │  Zone Nodes:        3 (32 cores, 64GB each)                          │   │
│  │  Bot Compute Nodes: 5 (32 cores, 32GB each)                          │   │
│  │  Coordinators:      3 (8 cores, 16GB each)                           │   │
│  │  Kafka:             3 brokers                                         │   │
│  │  ScyllaDB:          3 nodes                                           │   │
│  │  NATS:              3 nodes                                           │   │
│  │                                                                       │   │
│  │  Max Bots:          250,000                                           │   │
│  │  Monthly Cost:      ~$3,000-5,000                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  MEDIUM (Production)                                                  │   │
│  │                                                                       │   │
│  │  Zone Nodes:        10 (64 cores, 128GB each)                        │   │
│  │  Bot Compute Nodes: 20 (64 cores, 64GB each)                         │   │
│  │  Coordinators:      5 (16 cores, 32GB each)                          │   │
│  │  Kafka:             6 brokers                                         │   │
│  │  ScyllaDB:          6 nodes                                           │   │
│  │  NATS:              5 nodes                                           │   │
│  │                                                                       │   │
│  │  Max Bots:          1,500,000                                         │   │
│  │  Monthly Cost:      ~$15,000-25,000                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  LARGE (Enterprise)                                                   │   │
│  │                                                                       │   │
│  │  Zone Nodes:        50 (96 cores, 256GB each)                        │   │
│  │  Bot Compute Nodes: 100 (64 cores, 64GB each)                        │   │
│  │  Coordinators:      7 (32 cores, 64GB each)                          │   │
│  │  Kafka:             12 brokers                                        │   │
│  │  ScyllaDB:          12 nodes                                          │   │
│  │  NATS:              7 nodes                                           │   │
│  │                                                                       │   │
│  │  Max Bots:          10,000,000                                        │   │
│  │  Monthly Cost:      ~$100,000-150,000                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Cost Modeling

### Cloud Cost Breakdown (AWS)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Monthly Cost Breakdown (Medium Config)                    │
│                                                                              │
│  Compute (EC2):                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Zone Nodes:        10 × c6i.16xlarge    × $2.45/hr = $17,640       │   │
│  │  Bot Compute:       20 × c6i.16xlarge    × $2.45/hr = $35,280       │   │
│  │  Coordinators:      5  × c6i.4xlarge     × $0.68/hr = $2,448        │   │
│  │  Kafka:             6  × i3.2xlarge      × $0.62/hr = $2,678        │   │
│  │  ScyllaDB:          6  × i3.2xlarge      × $0.62/hr = $2,678        │   │
│  │  NATS:              5  × c6i.xlarge      × $0.17/hr = $612          │   │
│  │                                                                       │   │
│  │  Subtotal:          $61,336                                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Storage:                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  EBS (Zone Nodes):  10 × 500GB gp3       × $0.08/GB = $400          │   │
│  │  EBS (Kafka):       6  × 2TB   gp3       × $0.08/GB = $960          │   │
│  │  S3 (Backups):      10TB                 × $0.023/GB = $230         │   │
│  │                                                                       │   │
│  │  Subtotal:          $1,590                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Network:                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Data Transfer:     50TB internal        × $0.01/GB = $500          │   │
│  │  NAT Gateway:       (if needed)                     = $500          │   │
│  │                                                                       │   │
│  │  Subtotal:          $1,000                                            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Managed Services (optional):                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Amazon MSK:        6 brokers kafka.m5.2xlarge     = $2,500         │   │
│  │  (Alternative to self-managed Kafka)                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ═══════════════════════════════════════════════════════════════════════   │
│  TOTAL (self-managed):  ~$64,000/month                                      │
│  TOTAL (with managed):  ~$67,000/month                                      │
│                                                                              │
│  Cost per 1M bots:      ~$43/month                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Reserved Instance Savings

| Term | Discount | 1M Bots Cost |
|------|----------|--------------|
| On-Demand | 0% | $43/month |
| 1-Year Reserved | 35% | $28/month |
| 3-Year Reserved | 60% | $17/month |

### Spot Instance Strategy

```cpp
// Bot Compute Nodes are ideal for spot instances
// - Stateless (no data loss on termination)
// - Fault-tolerant (bots reassign automatically)
// - Flexible (can scale up/down quickly)

// Spot savings: 60-80% off on-demand
// Risk: Interruption with 2-minute warning

class SpotInstanceManager {
    void handle_spot_interruption(NodeId node) {
        // 1. Stop accepting new bot assignments
        node_registry.mark_draining(node);

        // 2. Migrate bots to other nodes
        for (EntityId bot : get_assigned_bots(node)) {
            NodeId new_node = find_available_node();
            reassign_bot(bot, new_node);
        }

        // 3. Allow graceful shutdown
        // (2 minutes is plenty for bot migration)
    }
};
```

## Scaling Strategies

### Horizontal Scaling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Horizontal Scaling Flow                                 │
│                                                                              │
│  Load Metrics                  Scaling Decision               Action        │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                              │
│  Zone Node CPU > 70%    ──►    Add Zone Node      ──►    Split cells to    │
│  for 5 minutes                                           new node           │
│                                                                              │
│  Zone Node CPU < 30%    ──►    Remove Zone Node   ──►    Merge cells to    │
│  for 15 minutes                                          other nodes        │
│                                                                              │
│  Bot Compute CPU > 80%  ──►    Add Bot Compute    ──►    Redistribute      │
│  for 5 minutes                                           bots               │
│                                                                              │
│  Bot Compute CPU < 20%  ──►    Remove Bot Compute ──►    Consolidate       │
│  for 15 minutes                                          bots               │
│                                                                              │
│  Cell entity count      ──►    Split Cell         ──►    Create sub-cells  │
│  > 50,000                                                on new nodes       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Auto-Scaling Configuration

```yaml
# kubernetes-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: zone-node-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: zone-node
  minReplicas: 3
  maxReplicas: 100
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

### Predictive Scaling

```cpp
class PredictiveScaler {
    // Use historical data to predict load
    TimeSeriesPredictor predictor;

public:
    void update_prediction() {
        // Get next hour's predicted load
        auto prediction = predictor.predict(std::chrono::hours(1));

        // Calculate required capacity
        int required_zone_nodes = calculate_zone_nodes(prediction.entity_count);
        int required_bot_nodes = calculate_bot_nodes(prediction.bot_count);

        // Pre-scale if needed (10 min ahead of predicted spike)
        if (prediction.spike_in < std::chrono::minutes(10)) {
            scale_to(required_zone_nodes, required_bot_nodes);
        }
    }

private:
    int calculate_zone_nodes(uint64_t entity_count) {
        const int ENTITIES_PER_NODE = 150000;  // Conservative
        return (entity_count / ENTITIES_PER_NODE) + 1;
    }

    int calculate_bot_nodes(uint64_t bot_count) {
        const int BOTS_PER_NODE = 60000;  // Conservative
        return (bot_count / BOTS_PER_NODE) + 1;
    }
};
```

## Bottleneck Analysis

### Common Bottlenecks

| Bottleneck | Symptom | Solution |
|------------|---------|----------|
| Zone Node CPU | High entity count, combat | Split cells, add nodes |
| Bot Compute CPU | Slow AI decisions | Add bot nodes, simplify AI |
| Message Bus | High latency, dropped msgs | Add NATS nodes, rate limit |
| Kafka | Consumer lag | Add partitions, more brokers |
| ScyllaDB | Query latency | Add nodes, tune compaction |
| Network | High cross-node traffic | Better cell assignment, compression |

### Monitoring Dashboards

```yaml
# grafana-dashboard.yaml
panels:
  - title: "Cluster Capacity"
    queries:
      - expr: sum(zone_node_entity_count) / sum(zone_node_capacity)
        legend: "Zone Node Utilization"
      - expr: sum(bot_compute_bot_count) / sum(bot_compute_capacity)
        legend: "Bot Compute Utilization"

  - title: "Scaling Headroom"
    queries:
      - expr: (sum(zone_node_capacity) - sum(zone_node_entity_count)) / 1000
        legend: "Zone Node Headroom (K entities)"
      - expr: (sum(bot_compute_capacity) - sum(bot_compute_bot_count)) / 1000
        legend: "Bot Compute Headroom (K bots)"

  - title: "Hot Cells"
    queries:
      - expr: topk(10, cell_entity_count)
        legend: "Top 10 Cells by Entity Count"
      - expr: topk(10, cell_events_per_second)
        legend: "Top 10 Cells by Events/sec"
```

## Capacity Planning Formulas

```python
# Capacity Planning Calculator

def calculate_cluster_size(target_bots: int, workload: str) -> dict:
    """Calculate required cluster size for target bot count."""

    # Workload multipliers
    WORKLOAD_FACTORS = {
        "idle": 1.0,
        "active": 2.5,
        "combat": 5.0,
        "raid": 8.0
    }

    factor = WORKLOAD_FACTORS.get(workload, 2.5)
    effective_bots = target_bots * factor

    # Base capacities (conservative)
    BOTS_PER_BOT_NODE = 60000
    ENTITIES_PER_ZONE_NODE = 100000

    # Calculations
    bot_nodes = max(3, int(effective_bots / BOTS_PER_BOT_NODE) + 1)
    zone_nodes = max(3, int((target_bots * 1.5) / ENTITIES_PER_ZONE_NODE) + 1)
    coordinators = min(7, max(3, zone_nodes // 10 + 3))

    # Supporting infrastructure
    kafka_brokers = max(3, zone_nodes // 5 + 3)
    scylla_nodes = max(3, zone_nodes // 5 + 3)
    nats_nodes = max(3, coordinators)

    return {
        "target_bots": target_bots,
        "workload": workload,
        "zone_nodes": zone_nodes,
        "bot_nodes": bot_nodes,
        "coordinators": coordinators,
        "kafka_brokers": kafka_brokers,
        "scylla_nodes": scylla_nodes,
        "nats_nodes": nats_nodes,
        "estimated_monthly_cost_usd": estimate_cost(
            zone_nodes, bot_nodes, coordinators,
            kafka_brokers, scylla_nodes, nats_nodes
        )
    }

def estimate_cost(zone, bot, coord, kafka, scylla, nats) -> int:
    """Estimate monthly AWS cost in USD."""
    ZONE_NODE_COST = 1800      # c6i.16xlarge
    BOT_NODE_COST = 1800       # c6i.16xlarge
    COORDINATOR_COST = 500     # c6i.4xlarge
    KAFKA_COST = 450           # i3.2xlarge
    SCYLLA_COST = 450          # i3.2xlarge
    NATS_COST = 125            # c6i.xlarge

    return (
        zone * ZONE_NODE_COST +
        bot * BOT_NODE_COST +
        coord * COORDINATOR_COST +
        kafka * KAFKA_COST +
        scylla * SCYLLA_COST +
        nats * NATS_COST +
        2000  # Storage, network, misc
    )

# Example usage:
# calculate_cluster_size(1_000_000, "active")
# => {"zone_nodes": 18, "bot_nodes": 45, ..., "estimated_monthly_cost_usd": 95000}
```

## Next Steps

- [09-implementation-roadmap.md](09-implementation-roadmap.md) - How to build this incrementally
- [07-failure-handling.md](07-failure-handling.md) - Capacity for resilience
