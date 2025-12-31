/*
 * Shared Memory IPC for Bot Engine
 *
 * Provides lock-free communication between worldserver and bot-engine process.
 *
 * Memory Layout:
 * ┌─────────────────────────────────────────────────────────────────┐
 * │ Header (64 bytes)                                                │
 * │   - Magic, version, sizes, state flags                          │
 * ├─────────────────────────────────────────────────────────────────┤
 * │ World Updates Ring Buffer (worldserver → bot-engine)            │
 * │   - Position, health, combat state updates                      │
 * ├─────────────────────────────────────────────────────────────────┤
 * │ Bot Actions Ring Buffer (bot-engine → worldserver)              │
 * │   - Movement, spell casts, target changes                       │
 * ├─────────────────────────────────────────────────────────────────┤
 * │ Entity Snapshot Area                                             │
 * │   - Current state of all visible entities                       │
 * └─────────────────────────────────────────────────────────────────┘
 */

#ifndef _PLAYERBOT_ECS_IPC_SHARED_MEMORY_H
#define _PLAYERBOT_ECS_IPC_SHARED_MEMORY_H

#include <cstdint>
#include <atomic>
#include <string>

namespace ecs {
namespace ipc {

// Magic number to identify valid shared memory
constexpr uint32_t SHM_MAGIC = 0x424F5453;  // "BOTS"
constexpr uint32_t SHM_VERSION = 1;

// Default sizes
constexpr size_t DEFAULT_UPDATE_RING_SIZE = 65536;    // 64K entries
constexpr size_t DEFAULT_ACTION_RING_SIZE = 16384;    // 16K entries
constexpr size_t DEFAULT_MAX_ENTITIES = 100000;       // 100K entities

/*
 * SharedMemoryHeader - Control block at start of shared memory
 *
 * Layout: 128 bytes (2 cache lines) for proper atomic alignment
 */
struct alignas(64) SharedMemoryHeader
{
    // First cache line - configuration (read-only after init)
    uint32_t magic = SHM_MAGIC;
    uint32_t version = SHM_VERSION;
    uint32_t updateRingSize = 0;
    uint32_t actionRingSize = 0;
    uint32_t maxEntities = 0;
    uint32_t updateRingOffset = 0;
    uint32_t actionRingOffset = 0;
    uint32_t entitySnapshotOffset = 0;
    uint32_t reserved1[8] = {};  // Pad to 64 bytes

    // Second cache line - mutable state (atomics)
    alignas(8) std::atomic<uint32_t> worldserverState{0};
    alignas(8) std::atomic<uint32_t> botEngineState{0};
    alignas(8) std::atomic<uint64_t> worldserverHeartbeat{0};
    alignas(8) std::atomic<uint64_t> botEngineHeartbeat{0};
    alignas(8) std::atomic<uint64_t> updatesSent{0};
    alignas(8) std::atomic<uint64_t> actionsReceived{0};
    uint8_t reserved2[16] = {};  // Pad to 64 bytes
};

static_assert(sizeof(SharedMemoryHeader) == 128, "Header must be 128 bytes");

/*
 * EntityUpdate - World state update sent to bot-engine
 */
struct EntityUpdate
{
    enum class Type : uint8_t
    {
        None = 0,
        PositionUpdate,
        VitalsUpdate,
        CombatStateUpdate,
        EntitySpawn,
        EntityDespawn,
        TargetChange,
        AuraUpdate,
        Full  // Full entity snapshot
    };

    uint64_t entityGuid = 0;
    uint64_t timestamp = 0;
    Type type = Type::None;
    uint8_t flags = 0;
    uint16_t dataSize = 0;
    uint32_t padding1 = 0;

    // Inline data for common updates
    union {
        struct {
            float x, y, z, orientation;
            uint32_t mapId;
            uint32_t padding;
        } position;

        struct {
            uint32_t health;
            uint32_t maxHealth;
            uint32_t power;
            uint32_t maxPower;
            uint32_t padding[2];
        } vitals;

        struct {
            uint8_t combatFlags;
            uint8_t padding[7];
            uint64_t targetGuid;
            uint64_t padding2;
        } combat;

        uint8_t rawData[24];
    } data = {};
};

/*
 * BotAction - Action request from bot-engine to worldserver
 */
struct BotAction
{
    enum class Type : uint8_t
    {
        None = 0,
        MoveTo,
        StopMove,
        CastSpell,
        Attack,
        StopAttack,
        SetTarget,
        ClearTarget,
        UseItem,
        Interact,
        Say,
        Emote
    };

    uint64_t botGuid = 0;
    uint64_t timestamp = 0;
    Type type = Type::None;
    uint8_t priority = 0;  // Higher = more urgent
    uint16_t dataSize = 0;
    uint32_t padding1 = 0;

    union {
        struct {
            float x, y, z;
            uint32_t mapId;
            uint32_t padding[2];
        } moveTo;

        struct {
            uint32_t spellId;
            uint32_t padding;
            uint64_t targetGuid;
            uint64_t padding2;
        } castSpell;

        struct {
            uint64_t targetGuid;
            uint64_t padding[2];
        } target;

        struct {
            uint32_t itemId;
            uint32_t padding;
            uint64_t targetGuid;
            uint64_t padding2;
        } useItem;

        uint8_t rawData[24];
    } data = {};
};

/*
 * EntitySnapshot - Full state for an entity in the snapshot area
 */
struct EntitySnapshot
{
    uint64_t guid = 0;
    uint64_t lastUpdate = 0;

    // Position
    float x = 0, y = 0, z = 0, orientation = 0;
    uint32_t mapId = 0;
    uint32_t zoneId = 0;

    // Vitals
    uint32_t health = 0, maxHealth = 0;
    uint32_t power = 0, maxPower = 0;

    // State
    uint8_t combatFlags = 0;
    uint8_t classId = 0;
    uint8_t level = 0;
    uint8_t faction = 0;
    uint32_t padding1 = 0;

    // Target
    uint64_t targetGuid = 0;
};

/*
 * LockFreeRingBuffer - SPSC (Single Producer Single Consumer) ring buffer
 *
 * Lock-free for one writer and one reader.
 * Uses cache-line padding to prevent false sharing.
 */
template<typename T, size_t Capacity>
class LockFreeRingBuffer
{
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be power of 2");

public:
    LockFreeRingBuffer() = default;

    // Try to push an item (producer only)
    bool TryPush(const T& item)
    {
        uint64_t writePos = m_writePos.load(std::memory_order_relaxed);
        uint64_t readPos = m_readPos.load(std::memory_order_acquire);

        if (writePos - readPos >= Capacity)
        {
            return false;  // Buffer full
        }

        m_buffer[writePos & (Capacity - 1)] = item;
        m_writePos.store(writePos + 1, std::memory_order_release);
        return true;
    }

    // Try to pop an item (consumer only)
    bool TryPop(T& item)
    {
        uint64_t readPos = m_readPos.load(std::memory_order_relaxed);
        uint64_t writePos = m_writePos.load(std::memory_order_acquire);

        if (readPos >= writePos)
        {
            return false;  // Buffer empty
        }

        item = m_buffer[readPos & (Capacity - 1)];
        m_readPos.store(readPos + 1, std::memory_order_release);
        return true;
    }

    // Get number of items available
    size_t Size() const
    {
        uint64_t writePos = m_writePos.load(std::memory_order_acquire);
        uint64_t readPos = m_readPos.load(std::memory_order_acquire);
        return static_cast<size_t>(writePos - readPos);
    }

    bool IsEmpty() const { return Size() == 0; }
    bool IsFull() const { return Size() >= Capacity; }

    // Drain all items (consumer only)
    template<typename Func>
    size_t DrainAll(Func&& handler)
    {
        size_t count = 0;
        T item;
        while (TryPop(item))
        {
            handler(item);
            ++count;
        }
        return count;
    }

private:
    // Cache-line aligned to prevent false sharing
    alignas(64) std::atomic<uint64_t> m_writePos{0};
    alignas(64) std::atomic<uint64_t> m_readPos{0};
    alignas(64) T m_buffer[Capacity];
};

/*
 * SharedMemoryRegion - Manages a shared memory region
 */
class SharedMemoryRegion
{
public:
    SharedMemoryRegion() = default;
    ~SharedMemoryRegion();

    // Create a new shared memory region (server side)
    bool Create(const std::string& name, size_t size);

    // Open an existing shared memory region (client side)
    bool Open(const std::string& name);

    // Close the region
    void Close();

    // Get pointer to the memory
    void* GetPointer() const { return m_ptr; }
    size_t GetSize() const { return m_size; }
    bool IsOpen() const { return m_ptr != nullptr; }

    // Get typed pointer
    template<typename T>
    T* As() const { return static_cast<T*>(m_ptr); }

    template<typename T>
    T* At(size_t offset) const
    {
        return reinterpret_cast<T*>(static_cast<uint8_t*>(m_ptr) + offset);
    }

private:
    void* m_ptr = nullptr;
    size_t m_size = 0;
    std::string m_name;
    bool m_isOwner = false;

#ifdef _WIN32
    void* m_handle = nullptr;
#else
    int m_fd = -1;
#endif
};

/*
 * BotEngineIPC - High-level IPC interface
 *
 * Used by both worldserver and bot-engine to communicate.
 */
class BotEngineIPC
{
public:
    static BotEngineIPC& Instance()
    {
        static BotEngineIPC instance;
        return instance;
    }

    // Initialize as server (worldserver) or client (bot-engine)
    bool InitializeServer(const std::string& name = "swarm_bots");
    bool InitializeClient(const std::string& name = "swarm_bots");

    // Shutdown
    void Shutdown();

    bool IsInitialized() const { return m_initialized; }
    bool IsServer() const { return m_isServer; }

    // Server (worldserver) methods
    bool SendUpdate(const EntityUpdate& update);
    size_t DrainActions(void (*handler)(const BotAction& action));

    // Client (bot-engine) methods
    size_t DrainUpdates(void (*handler)(const EntityUpdate& update));
    bool SendAction(const BotAction& action);

    // Entity snapshot access
    EntitySnapshot* GetEntitySnapshot(uint64_t guid);
    void UpdateEntitySnapshot(uint64_t guid, const EntitySnapshot& snapshot);

    // Heartbeat
    void UpdateHeartbeat();
    bool IsPartnerAlive(uint64_t timeoutMs = 5000) const;

    // Statistics
    uint64_t GetUpdatesSent() const;
    uint64_t GetActionsReceived() const;

private:
    BotEngineIPC() = default;

    SharedMemoryRegion m_region;
    SharedMemoryHeader* m_header = nullptr;

    // Ring buffer pointers (point into shared memory)
    void* m_updateRing = nullptr;
    void* m_actionRing = nullptr;
    EntitySnapshot* m_entitySnapshots = nullptr;

    bool m_initialized = false;
    bool m_isServer = false;
};

#define sBotEngineIPC ecs::ipc::BotEngineIPC::Instance()

} // namespace ipc
} // namespace ecs

#endif // _PLAYERBOT_ECS_IPC_SHARED_MEMORY_H
