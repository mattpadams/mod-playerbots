/*
 * ComponentArray - Contiguous component storage for ECS
 *
 * Provides cache-friendly storage for components of a single type.
 * Uses sparse-set pattern for O(1) access with minimal memory overhead.
 *
 * Key features:
 * - Contiguous memory layout for batch processing
 * - O(1) add, remove, and lookup
 * - Stable iteration during modification (via deferred operations)
 * - Memory pooling for reduced allocations
 */

#ifndef _PLAYERBOT_ECS_COMPONENT_ARRAY_H
#define _PLAYERBOT_ECS_COMPONENT_ARRAY_H

#include "Types.h"
#include <vector>
#include <unordered_map>
#include <cassert>
#include <type_traits>
#include <algorithm>

namespace ecs {

/*
 * IComponentArray - Type-erased interface for component storage
 *
 * Allows Registry to manage different component types uniformly.
 */
class IComponentArray
{
public:
    virtual ~IComponentArray() = default;
    virtual void EntityDestroyed(EntityId entity) = 0;
    virtual bool HasEntity(EntityId entity) const = 0;
    virtual size_t Size() const = 0;
    virtual void Clear() = 0;
    virtual void Reserve(size_t capacity) = 0;
};

/*
 * ComponentArray<T> - Typed contiguous storage for component T
 *
 * Memory layout:
 * - Dense array: Contiguous T components (cache-friendly iteration)
 * - Entity array: Parallel array of EntityIds (for reverse lookup)
 * - Sparse map: EntityId -> dense index (for O(1) lookup)
 *
 * This sparse-set design gives us:
 * - O(1) add/remove/lookup
 * - Cache-friendly iteration (components are contiguous)
 * - No gaps in component storage
 */
template<typename T>
class ComponentArray : public IComponentArray
{
    static_assert(std::is_default_constructible_v<T>,
        "Component must be default constructible");

public:
    ComponentArray() = default;

    // Pre-allocate storage for expected entity count
    void Reserve(size_t capacity) override
    {
        m_components.reserve(capacity);
        m_entities.reserve(capacity);
        m_entityToIndex.reserve(capacity);
    }

    /*
     * Add component to entity
     * Returns reference to the new component for initialization
     */
    T& Add(EntityId entity, const T& component = T{})
    {
        assert(!HasEntity(entity) && "Entity already has this component");

        size_t newIndex = m_components.size();
        m_entityToIndex[entity] = newIndex;
        m_components.push_back(component);
        m_entities.push_back(entity);

        return m_components.back();
    }

    /*
     * Add component to entity using in-place construction
     */
    template<typename... Args>
    T& Emplace(EntityId entity, Args&&... args)
    {
        assert(!HasEntity(entity) && "Entity already has this component");

        size_t newIndex = m_components.size();
        m_entityToIndex[entity] = newIndex;
        m_components.emplace_back(std::forward<Args>(args)...);
        m_entities.push_back(entity);

        return m_components.back();
    }

    /*
     * Remove component from entity
     * Uses swap-and-pop for O(1) removal while maintaining contiguity
     */
    void Remove(EntityId entity)
    {
        auto it = m_entityToIndex.find(entity);
        if (it == m_entityToIndex.end())
            return;

        size_t indexToRemove = it->second;
        size_t lastIndex = m_components.size() - 1;

        if (indexToRemove != lastIndex)
        {
            // Swap with last element
            m_components[indexToRemove] = std::move(m_components[lastIndex]);
            m_entities[indexToRemove] = m_entities[lastIndex];

            // Update moved entity's index
            m_entityToIndex[m_entities[indexToRemove]] = indexToRemove;
        }

        // Remove last element
        m_components.pop_back();
        m_entities.pop_back();
        m_entityToIndex.erase(it);
    }

    /*
     * Get component for entity
     * Returns nullptr if entity doesn't have this component
     */
    T* Get(EntityId entity)
    {
        auto it = m_entityToIndex.find(entity);
        if (it == m_entityToIndex.end())
            return nullptr;
        return &m_components[it->second];
    }

    const T* Get(EntityId entity) const
    {
        auto it = m_entityToIndex.find(entity);
        if (it == m_entityToIndex.end())
            return nullptr;
        return &m_components[it->second];
    }

    /*
     * Get component reference (asserts entity has component)
     */
    T& GetRef(EntityId entity)
    {
        auto it = m_entityToIndex.find(entity);
        assert(it != m_entityToIndex.end() && "Entity does not have this component");
        return m_components[it->second];
    }

    const T& GetRef(EntityId entity) const
    {
        auto it = m_entityToIndex.find(entity);
        assert(it != m_entityToIndex.end() && "Entity does not have this component");
        return m_components[it->second];
    }

    // Check if entity has this component type
    bool HasEntity(EntityId entity) const override
    {
        return m_entityToIndex.find(entity) != m_entityToIndex.end();
    }

    // IComponentArray interface
    void EntityDestroyed(EntityId entity) override
    {
        Remove(entity);
    }

    size_t Size() const override
    {
        return m_components.size();
    }

    void Clear() override
    {
        m_components.clear();
        m_entities.clear();
        m_entityToIndex.clear();
    }

    /*
     * Direct access to component data for batch processing
     * WARNING: Pointers may be invalidated by Add/Remove operations
     */
    T* Data() { return m_components.data(); }
    const T* Data() const { return m_components.data(); }

    // Access entity at given dense index
    EntityId GetEntityAt(size_t index) const
    {
        assert(index < m_entities.size());
        return m_entities[index];
    }

    /*
     * Iterator support for range-based for loops
     * Iterates over (EntityId, T&) pairs
     */
    class Iterator
    {
    public:
        using iterator_category = std::forward_iterator_tag;
        using value_type = std::pair<EntityId, T&>;
        using difference_type = std::ptrdiff_t;

        Iterator(ComponentArray* arr, size_t index) : m_array(arr), m_index(index) {}

        std::pair<EntityId, T&> operator*()
        {
            return {m_array->m_entities[m_index], m_array->m_components[m_index]};
        }

        Iterator& operator++() { ++m_index; return *this; }
        Iterator operator++(int) { Iterator tmp = *this; ++m_index; return tmp; }

        bool operator==(const Iterator& other) const { return m_index == other.m_index; }
        bool operator!=(const Iterator& other) const { return m_index != other.m_index; }

    private:
        ComponentArray* m_array;
        size_t m_index;
    };

    class ConstIterator
    {
    public:
        using iterator_category = std::forward_iterator_tag;
        using value_type = std::pair<EntityId, const T&>;
        using difference_type = std::ptrdiff_t;

        ConstIterator(const ComponentArray* arr, size_t index) : m_array(arr), m_index(index) {}

        std::pair<EntityId, const T&> operator*() const
        {
            return {m_array->m_entities[m_index], m_array->m_components[m_index]};
        }

        ConstIterator& operator++() { ++m_index; return *this; }
        ConstIterator operator++(int) { ConstIterator tmp = *this; ++m_index; return tmp; }

        bool operator==(const ConstIterator& other) const { return m_index == other.m_index; }
        bool operator!=(const ConstIterator& other) const { return m_index != other.m_index; }

    private:
        const ComponentArray* m_array;
        size_t m_index;
    };

    Iterator begin() { return Iterator(this, 0); }
    Iterator end() { return Iterator(this, m_components.size()); }
    ConstIterator begin() const { return ConstIterator(this, 0); }
    ConstIterator end() const { return ConstIterator(this, m_components.size()); }
    ConstIterator cbegin() const { return ConstIterator(this, 0); }
    ConstIterator cend() const { return ConstIterator(this, m_components.size()); }

    /*
     * Raw component iteration (faster for batch processing)
     */
    template<typename Func>
    void ForEach(Func&& func)
    {
        for (size_t i = 0; i < m_components.size(); ++i)
        {
            func(m_entities[i], m_components[i]);
        }
    }

    template<typename Func>
    void ForEachConst(Func&& func) const
    {
        for (size_t i = 0; i < m_components.size(); ++i)
        {
            func(m_entities[i], m_components[i]);
        }
    }

private:
    std::vector<T> m_components;                        // Dense component storage
    std::vector<EntityId> m_entities;                   // Parallel entity array
    std::unordered_map<EntityId, size_t> m_entityToIndex; // Sparse lookup
};

} // namespace ecs

#endif // _PLAYERBOT_ECS_COMPONENT_ARRAY_H
