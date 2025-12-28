/*
 * Registry - Central ECS management class
 *
 * The Registry is the core of the ECS, managing:
 * - Entity creation and destruction
 * - Component storage and access
 * - Entity-component queries
 *
 * Thread-safety: The Registry is NOT thread-safe by default.
 * For multi-threaded access, use external synchronization or
 * partition entities across multiple registries.
 */

#ifndef _PLAYERBOT_ECS_REGISTRY_H
#define _PLAYERBOT_ECS_REGISTRY_H

#include "Types.h"
#include "ComponentArray.h"
#include <memory>
#include <vector>
#include <queue>
#include <unordered_map>
#include <unordered_set>
#include <functional>
#include <typeindex>

namespace ecs {

/*
 * Registry - Central entity and component manager
 */
class Registry
{
public:
    Registry() = default;
    ~Registry() = default;

    // Non-copyable, movable
    Registry(const Registry&) = delete;
    Registry& operator=(const Registry&) = delete;
    Registry(Registry&&) = default;
    Registry& operator=(Registry&&) = default;

    /*
     * Create a new entity of the given type
     */
    EntityId CreateEntity(EntityType type = EntityType::Bot)
    {
        EntityId id;

        if (!m_freeSlots.empty())
        {
            // Reuse a recycled slot with incremented generation
            uint32_t index = m_freeSlots.front();
            m_freeSlots.pop();

            uint32_t generation = m_generations[index] + 1;
            m_generations[index] = generation;

            id = EntityId(index, generation, static_cast<uint8_t>(type));
        }
        else
        {
            // Allocate new slot
            uint32_t index = static_cast<uint32_t>(m_generations.size());
            m_generations.push_back(0);

            id = EntityId(index, 0, static_cast<uint8_t>(type));
        }

        m_livingEntities.insert(id);
        return id;
    }

    /*
     * Destroy an entity and all its components
     */
    void DestroyEntity(EntityId entity)
    {
        if (!IsAlive(entity))
            return;

        // Notify all component arrays to remove this entity
        for (auto& [typeId, array] : m_componentArrays)
        {
            array->EntityDestroyed(entity);
        }

        // Recycle the slot
        m_freeSlots.push(entity.Index());
        m_livingEntities.erase(entity);
    }

    /*
     * Check if entity is still alive (not destroyed and generation matches)
     */
    bool IsAlive(EntityId entity) const
    {
        if (!entity.IsValid())
            return false;

        uint32_t index = entity.Index();
        if (index >= m_generations.size())
            return false;

        return m_generations[index] == entity.Generation() &&
               m_livingEntities.find(entity) != m_livingEntities.end();
    }

    /*
     * Get the type of an entity
     */
    EntityType GetEntityType(EntityId entity) const
    {
        return static_cast<EntityType>(entity.Type());
    }

    /*
     * Register a component type with the registry
     * Must be called before using the component type
     */
    template<typename T>
    void RegisterComponent()
    {
        ComponentTypeId typeId = ComponentType<T>::Id();

        if (m_componentArrays.find(typeId) != m_componentArrays.end())
            return; // Already registered

        m_componentArrays[typeId] = std::make_unique<ComponentArray<T>>();
    }

    /*
     * Add a component to an entity
     */
    template<typename T>
    T& AddComponent(EntityId entity, const T& component = T{})
    {
        return GetComponentArray<T>()->Add(entity, component);
    }

    /*
     * Add a component using in-place construction
     */
    template<typename T, typename... Args>
    T& EmplaceComponent(EntityId entity, Args&&... args)
    {
        return GetComponentArray<T>()->Emplace(entity, std::forward<Args>(args)...);
    }

    /*
     * Remove a component from an entity
     */
    template<typename T>
    void RemoveComponent(EntityId entity)
    {
        GetComponentArray<T>()->Remove(entity);
    }

    /*
     * Get a component from an entity (returns nullptr if not found)
     */
    template<typename T>
    T* GetComponent(EntityId entity)
    {
        auto* array = GetComponentArray<T>();
        return array ? array->Get(entity) : nullptr;
    }

    template<typename T>
    const T* GetComponent(EntityId entity) const
    {
        auto* array = GetComponentArray<T>();
        return array ? array->Get(entity) : nullptr;
    }

    /*
     * Check if entity has a component
     */
    template<typename T>
    bool HasComponent(EntityId entity) const
    {
        auto* array = GetComponentArray<T>();
        return array && array->HasEntity(entity);
    }

    /*
     * Check if entity has all specified components
     */
    template<typename... Components>
    bool HasComponents(EntityId entity) const
    {
        return (HasComponent<Components>(entity) && ...);
    }

    /*
     * Get component array for direct iteration
     */
    template<typename T>
    ComponentArray<T>* GetComponentArray()
    {
        ComponentTypeId typeId = ComponentType<T>::Id();
        auto it = m_componentArrays.find(typeId);
        if (it == m_componentArrays.end())
        {
            // Auto-register if not found
            RegisterComponent<T>();
            it = m_componentArrays.find(typeId);
        }
        return static_cast<ComponentArray<T>*>(it->second.get());
    }

    template<typename T>
    const ComponentArray<T>* GetComponentArray() const
    {
        ComponentTypeId typeId = ComponentType<T>::Id();
        auto it = m_componentArrays.find(typeId);
        if (it == m_componentArrays.end())
            return nullptr;
        return static_cast<const ComponentArray<T>*>(it->second.get());
    }

    /*
     * Iterate over entities with a specific component
     */
    template<typename T, typename Func>
    void ForEach(Func&& func)
    {
        auto* array = GetComponentArray<T>();
        if (array)
        {
            array->ForEach(std::forward<Func>(func));
        }
    }

    /*
     * Iterate over entities with multiple components
     * The callback receives (EntityId, T1&, T2&, ...)
     */
    template<typename T1, typename T2, typename... Rest, typename Func>
    void ForEach(Func&& func)
    {
        // Use smallest array as the iteration base
        auto* array1 = GetComponentArray<T1>();
        if (!array1 || array1->Size() == 0)
            return;

        for (auto it = array1->begin(); it != array1->end(); ++it)
        {
            auto [entity, comp1] = *it;
            if (HasComponents<T2, Rest...>(entity))
            {
                func(entity, comp1, *GetComponent<T2>(entity), (*GetComponent<Rest>(entity))...);
            }
        }
    }

    /*
     * Get count of entities with a specific component
     */
    template<typename T>
    size_t Count() const
    {
        auto* array = GetComponentArray<T>();
        return array ? array->Size() : 0;
    }

    /*
     * Get all living entities
     */
    const std::unordered_set<EntityId>& GetLivingEntities() const
    {
        return m_livingEntities;
    }

    /*
     * Get count of all living entities
     */
    size_t EntityCount() const
    {
        return m_livingEntities.size();
    }

    /*
     * Clear all entities and components
     */
    void Clear()
    {
        for (auto& [typeId, array] : m_componentArrays)
        {
            array->Clear();
        }
        m_livingEntities.clear();
        m_generations.clear();
        while (!m_freeSlots.empty())
            m_freeSlots.pop();
    }

    /*
     * Reserve capacity for expected entity count
     */
    void Reserve(size_t entityCount)
    {
        m_generations.reserve(entityCount);
        m_livingEntities.reserve(entityCount);
        for (auto& [typeId, array] : m_componentArrays)
        {
            array->Reserve(entityCount);
        }
    }

private:
    // Entity management
    std::vector<uint32_t> m_generations;              // Generation counter per slot
    std::queue<uint32_t> m_freeSlots;                 // Recycled slot indices
    std::unordered_set<EntityId> m_livingEntities;    // Currently alive entities

    // Component storage (type-erased)
    std::unordered_map<ComponentTypeId, std::unique_ptr<IComponentArray>> m_componentArrays;
};

/*
 * View - Query helper for iterating entities with specific components
 *
 * Usage:
 *   auto view = View<Position, Velocity>(registry);
 *   for (auto [entity, pos, vel] : view) { ... }
 */
template<typename... Components>
class View
{
public:
    explicit View(Registry& registry) : m_registry(registry) {}

    class Iterator
    {
    public:
        Iterator(Registry& registry, typename std::unordered_set<EntityId>::const_iterator it,
                 typename std::unordered_set<EntityId>::const_iterator end)
            : m_registry(registry), m_it(it), m_end(end)
        {
            AdvanceToValid();
        }

        auto operator*()
        {
            return std::tuple<EntityId, Components&...>(
                *m_it,
                *m_registry.template GetComponent<Components>(*m_it)...
            );
        }

        Iterator& operator++()
        {
            ++m_it;
            AdvanceToValid();
            return *this;
        }

        bool operator!=(const Iterator& other) const { return m_it != other.m_it; }

    private:
        void AdvanceToValid()
        {
            while (m_it != m_end && !m_registry.template HasComponents<Components...>(*m_it))
            {
                ++m_it;
            }
        }

        Registry& m_registry;
        typename std::unordered_set<EntityId>::const_iterator m_it;
        typename std::unordered_set<EntityId>::const_iterator m_end;
    };

    Iterator begin()
    {
        const auto& entities = m_registry.GetLivingEntities();
        return Iterator(m_registry, entities.begin(), entities.end());
    }

    Iterator end()
    {
        const auto& entities = m_registry.GetLivingEntities();
        return Iterator(m_registry, entities.end(), entities.end());
    }

private:
    Registry& m_registry;
};

} // namespace ecs

#endif // _PLAYERBOT_ECS_REGISTRY_H
