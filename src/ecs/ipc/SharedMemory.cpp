/*
 * Shared Memory IPC Implementation
 */

#include "SharedMemory.h"
#include "Log.h"

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#endif

#include <chrono>

namespace ecs {
namespace ipc {

// =============================================================================
// SharedMemoryRegion
// =============================================================================

SharedMemoryRegion::~SharedMemoryRegion()
{
    Close();
}

bool SharedMemoryRegion::Create(const std::string& name, size_t size)
{
    if (m_ptr)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: Already open");
        return false;
    }

    m_name = name;
    m_size = size;
    m_isOwner = true;

#ifdef _WIN32
    m_handle = CreateFileMappingA(
        INVALID_HANDLE_VALUE,
        nullptr,
        PAGE_READWRITE,
        static_cast<DWORD>(size >> 32),
        static_cast<DWORD>(size & 0xFFFFFFFF),
        name.c_str()
    );

    if (!m_handle)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: CreateFileMapping failed: {}", GetLastError());
        return false;
    }

    m_ptr = MapViewOfFile(m_handle, FILE_MAP_ALL_ACCESS, 0, 0, size);
    if (!m_ptr)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: MapViewOfFile failed: {}", GetLastError());
        CloseHandle(m_handle);
        m_handle = nullptr;
        return false;
    }

#else
    // Create shared memory object
    std::string shmName = "/" + name;
    m_fd = shm_open(shmName.c_str(), O_CREAT | O_RDWR, 0666);
    if (m_fd == -1)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: shm_open failed: {}", strerror(errno));
        return false;
    }

    // Set size
    if (ftruncate(m_fd, static_cast<off_t>(size)) == -1)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: ftruncate failed: {}", strerror(errno));
        close(m_fd);
        shm_unlink(shmName.c_str());
        m_fd = -1;
        return false;
    }

    // Map to memory
    m_ptr = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED, m_fd, 0);
    if (m_ptr == MAP_FAILED)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: mmap failed: {}", strerror(errno));
        close(m_fd);
        shm_unlink(shmName.c_str());
        m_fd = -1;
        m_ptr = nullptr;
        return false;
    }
#endif

    // Zero-initialize
    std::memset(m_ptr, 0, size);

    LOG_INFO("playerbots", "SharedMemoryRegion: Created '{}' ({} bytes)", name, size);
    return true;
}

bool SharedMemoryRegion::Open(const std::string& name)
{
    if (m_ptr)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: Already open");
        return false;
    }

    m_name = name;
    m_isOwner = false;

#ifdef _WIN32
    m_handle = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name.c_str());
    if (!m_handle)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: OpenFileMapping failed: {}", GetLastError());
        return false;
    }

    // Get size from mapping
    MEMORY_BASIC_INFORMATION info;
    m_ptr = MapViewOfFile(m_handle, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!m_ptr)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: MapViewOfFile failed: {}", GetLastError());
        CloseHandle(m_handle);
        m_handle = nullptr;
        return false;
    }

    VirtualQuery(m_ptr, &info, sizeof(info));
    m_size = info.RegionSize;

#else
    std::string shmName = "/" + name;
    m_fd = shm_open(shmName.c_str(), O_RDWR, 0666);
    if (m_fd == -1)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: shm_open failed: {}", strerror(errno));
        return false;
    }

    // Get size
    struct stat st;
    if (fstat(m_fd, &st) == -1)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: fstat failed: {}", strerror(errno));
        close(m_fd);
        m_fd = -1;
        return false;
    }
    m_size = static_cast<size_t>(st.st_size);

    // Map to memory
    m_ptr = mmap(nullptr, m_size, PROT_READ | PROT_WRITE, MAP_SHARED, m_fd, 0);
    if (m_ptr == MAP_FAILED)
    {
        LOG_ERROR("playerbots", "SharedMemoryRegion: mmap failed: {}", strerror(errno));
        close(m_fd);
        m_fd = -1;
        m_ptr = nullptr;
        return false;
    }
#endif

    LOG_INFO("playerbots", "SharedMemoryRegion: Opened '{}' ({} bytes)", name, m_size);
    return true;
}

void SharedMemoryRegion::Close()
{
    if (!m_ptr)
        return;

#ifdef _WIN32
    UnmapViewOfFile(m_ptr);
    if (m_handle)
    {
        CloseHandle(m_handle);
        m_handle = nullptr;
    }
#else
    munmap(m_ptr, m_size);
    if (m_fd != -1)
    {
        close(m_fd);
        if (m_isOwner)
        {
            std::string shmName = "/" + m_name;
            shm_unlink(shmName.c_str());
        }
        m_fd = -1;
    }
#endif

    LOG_INFO("playerbots", "SharedMemoryRegion: Closed '{}'", m_name);
    m_ptr = nullptr;
    m_size = 0;
}

// =============================================================================
// BotEngineIPC
// =============================================================================

// Fixed-size ring buffers for shared memory
using UpdateRingBuffer = LockFreeRingBuffer<EntityUpdate, 65536>;
using ActionRingBuffer = LockFreeRingBuffer<BotAction, 16384>;

bool BotEngineIPC::InitializeServer(const std::string& name)
{
    if (m_initialized)
    {
        LOG_ERROR("playerbots", "BotEngineIPC: Already initialized");
        return false;
    }

    // Calculate total size needed
    size_t headerSize = sizeof(SharedMemoryHeader);
    size_t updateRingSize = sizeof(UpdateRingBuffer);
    size_t actionRingSize = sizeof(ActionRingBuffer);
    size_t snapshotSize = sizeof(EntitySnapshot) * DEFAULT_MAX_ENTITIES;

    size_t totalSize = headerSize + updateRingSize + actionRingSize + snapshotSize;

    // Create shared memory
    if (!m_region.Create(name, totalSize))
    {
        return false;
    }

    // Initialize header
    m_header = m_region.As<SharedMemoryHeader>();
    m_header->magic = SHM_MAGIC;
    m_header->version = SHM_VERSION;
    m_header->updateRingSize = static_cast<uint32_t>(updateRingSize);
    m_header->actionRingSize = static_cast<uint32_t>(actionRingSize);
    m_header->maxEntities = DEFAULT_MAX_ENTITIES;

    // Set offsets
    m_header->updateRingOffset = static_cast<uint32_t>(headerSize);
    m_header->actionRingOffset = static_cast<uint32_t>(headerSize + updateRingSize);
    m_header->entitySnapshotOffset = static_cast<uint32_t>(headerSize + updateRingSize + actionRingSize);

    // Get pointers to ring buffers
    m_updateRing = m_region.At<void>(m_header->updateRingOffset);
    m_actionRing = m_region.At<void>(m_header->actionRingOffset);
    m_entitySnapshots = m_region.At<EntitySnapshot>(m_header->entitySnapshotOffset);

    // Construct ring buffers in place
    new (m_updateRing) UpdateRingBuffer();
    new (m_actionRing) ActionRingBuffer();

    // Mark server as running
    m_header->worldserverState.store(1, std::memory_order_release);
    UpdateHeartbeat();

    m_initialized = true;
    m_isServer = true;

    LOG_INFO("playerbots", "BotEngineIPC: Server initialized ({}MB shared memory)",
        totalSize / (1024 * 1024));
    return true;
}

bool BotEngineIPC::InitializeClient(const std::string& name)
{
    if (m_initialized)
    {
        LOG_ERROR("playerbots", "BotEngineIPC: Already initialized");
        return false;
    }

    // Open existing shared memory
    if (!m_region.Open(name))
    {
        return false;
    }

    // Validate header
    m_header = m_region.As<SharedMemoryHeader>();
    if (m_header->magic != SHM_MAGIC)
    {
        LOG_ERROR("playerbots", "BotEngineIPC: Invalid magic number");
        m_region.Close();
        return false;
    }

    if (m_header->version != SHM_VERSION)
    {
        LOG_ERROR("playerbots", "BotEngineIPC: Version mismatch ({} vs {})",
            m_header->version, SHM_VERSION);
        m_region.Close();
        return false;
    }

    // Get pointers to ring buffers
    m_updateRing = m_region.At<void>(m_header->updateRingOffset);
    m_actionRing = m_region.At<void>(m_header->actionRingOffset);
    m_entitySnapshots = m_region.At<EntitySnapshot>(m_header->entitySnapshotOffset);

    // Mark client as running
    m_header->botEngineState.store(1, std::memory_order_release);
    UpdateHeartbeat();

    m_initialized = true;
    m_isServer = false;

    LOG_INFO("playerbots", "BotEngineIPC: Client initialized");
    return true;
}

void BotEngineIPC::Shutdown()
{
    if (!m_initialized)
        return;

    // Mark as shutting down
    if (m_isServer)
    {
        m_header->worldserverState.store(2, std::memory_order_release);
    }
    else
    {
        m_header->botEngineState.store(2, std::memory_order_release);
    }

    m_region.Close();
    m_header = nullptr;
    m_updateRing = nullptr;
    m_actionRing = nullptr;
    m_entitySnapshots = nullptr;
    m_initialized = false;

    LOG_INFO("playerbots", "BotEngineIPC: Shutdown complete");
}

bool BotEngineIPC::SendUpdate(const EntityUpdate& update)
{
    if (!m_initialized || !m_isServer)
        return false;

    auto* ring = static_cast<UpdateRingBuffer*>(m_updateRing);
    if (ring->TryPush(update))
    {
        m_header->updatesSent.fetch_add(1, std::memory_order_relaxed);
        return true;
    }
    return false;
}

size_t BotEngineIPC::DrainActions(void (*handler)(const BotAction& action))
{
    if (!m_initialized || !m_isServer || !handler)
        return 0;

    auto* ring = static_cast<ActionRingBuffer*>(m_actionRing);
    size_t count = 0;
    BotAction action;

    while (ring->TryPop(action))
    {
        handler(action);
        m_header->actionsReceived.fetch_add(1, std::memory_order_relaxed);
        ++count;
    }

    return count;
}

size_t BotEngineIPC::DrainUpdates(void (*handler)(const EntityUpdate& update))
{
    if (!m_initialized || m_isServer || !handler)
        return 0;

    auto* ring = static_cast<UpdateRingBuffer*>(m_updateRing);
    size_t count = 0;
    EntityUpdate update;

    while (ring->TryPop(update))
    {
        handler(update);
        ++count;
    }

    return count;
}

bool BotEngineIPC::SendAction(const BotAction& action)
{
    if (!m_initialized || m_isServer)
        return false;

    auto* ring = static_cast<ActionRingBuffer*>(m_actionRing);
    return ring->TryPush(action);
}

EntitySnapshot* BotEngineIPC::GetEntitySnapshot(uint64_t guid)
{
    if (!m_initialized || !m_entitySnapshots)
        return nullptr;

    // Simple hash-based lookup (could be improved with a proper hash table)
    size_t index = guid % m_header->maxEntities;

    // Linear probe for matching guid or empty slot
    for (size_t i = 0; i < 16; ++i)  // Max 16 probes
    {
        size_t idx = (index + i) % m_header->maxEntities;
        if (m_entitySnapshots[idx].guid == guid)
        {
            return &m_entitySnapshots[idx];
        }
        if (m_entitySnapshots[idx].guid == 0)
        {
            return nullptr;  // Not found
        }
    }

    return nullptr;
}

void BotEngineIPC::UpdateEntitySnapshot(uint64_t guid, const EntitySnapshot& snapshot)
{
    if (!m_initialized || !m_entitySnapshots)
        return;

    size_t index = guid % m_header->maxEntities;

    // Linear probe for matching guid or empty slot
    for (size_t i = 0; i < 16; ++i)
    {
        size_t idx = (index + i) % m_header->maxEntities;
        if (m_entitySnapshots[idx].guid == guid || m_entitySnapshots[idx].guid == 0)
        {
            m_entitySnapshots[idx] = snapshot;
            return;
        }
    }

    // Table too full - overwrite at hash position
    m_entitySnapshots[index] = snapshot;
}

void BotEngineIPC::UpdateHeartbeat()
{
    if (!m_initialized || !m_header)
        return;

    auto now = std::chrono::steady_clock::now().time_since_epoch();
    uint64_t ms = std::chrono::duration_cast<std::chrono::milliseconds>(now).count();

    if (m_isServer)
    {
        m_header->worldserverHeartbeat.store(ms, std::memory_order_release);
    }
    else
    {
        m_header->botEngineHeartbeat.store(ms, std::memory_order_release);
    }
}

bool BotEngineIPC::IsPartnerAlive(uint64_t timeoutMs) const
{
    if (!m_initialized || !m_header)
        return false;

    auto now = std::chrono::steady_clock::now().time_since_epoch();
    uint64_t ms = std::chrono::duration_cast<std::chrono::milliseconds>(now).count();

    uint64_t partnerHeartbeat;
    if (m_isServer)
    {
        partnerHeartbeat = m_header->botEngineHeartbeat.load(std::memory_order_acquire);
    }
    else
    {
        partnerHeartbeat = m_header->worldserverHeartbeat.load(std::memory_order_acquire);
    }

    return (ms - partnerHeartbeat) < timeoutMs;
}

uint64_t BotEngineIPC::GetUpdatesSent() const
{
    return m_header ? m_header->updatesSent.load(std::memory_order_relaxed) : 0;
}

uint64_t BotEngineIPC::GetActionsReceived() const
{
    return m_header ? m_header->actionsReceived.load(std::memory_order_relaxed) : 0;
}

} // namespace ipc
} // namespace ecs
