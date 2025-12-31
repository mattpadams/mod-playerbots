/*
 * Shared Memory Standalone Wrapper
 *
 * This file includes the SharedMemory implementation with standalone logging.
 */

// Include our standalone log shim before SharedMemory.cpp
#include "StandaloneLog.h"

// Now include the actual implementation
// We need to prevent it from including Log.h by defining it as included
#define LOG_H

#include "../../src/ecs/ipc/SharedMemory.cpp"
