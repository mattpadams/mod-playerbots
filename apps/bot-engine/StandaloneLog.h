/*
 * Standalone Logging Shim for Bot Engine
 *
 * Provides LOG_* macros that redirect to stdout/stderr
 * when building outside of AzerothCore.
 */

#ifndef _STANDALONE_LOG_H
#define _STANDALONE_LOG_H

#ifdef BOT_ENGINE_STANDALONE

#include <iostream>
#include <sstream>

// Simple log macros for standalone build
#define LOG_INFO(filter, fmt, ...) \
    do { \
        std::cout << "[INFO] " << FormatLog(fmt, ##__VA_ARGS__) << std::endl; \
    } while(0)

#define LOG_ERROR(filter, fmt, ...) \
    do { \
        std::cerr << "[ERROR] " << FormatLog(fmt, ##__VA_ARGS__) << std::endl; \
    } while(0)

#define LOG_WARN(filter, fmt, ...) \
    do { \
        std::cout << "[WARN] " << FormatLog(fmt, ##__VA_ARGS__) << std::endl; \
    } while(0)

#define LOG_DEBUG(filter, fmt, ...) \
    do { \
        std::cout << "[DEBUG] " << FormatLog(fmt, ##__VA_ARGS__) << std::endl; \
    } while(0)

// Simple format helper (basic {} replacement)
template<typename... Args>
std::string FormatLog(const char* fmt, Args&&... args)
{
    std::ostringstream oss;
    FormatLogImpl(oss, fmt, std::forward<Args>(args)...);
    return oss.str();
}

inline void FormatLogImpl(std::ostringstream& oss, const char* fmt)
{
    oss << fmt;
}

template<typename T, typename... Args>
void FormatLogImpl(std::ostringstream& oss, const char* fmt, T&& value, Args&&... args)
{
    while (*fmt)
    {
        if (*fmt == '{' && *(fmt + 1) == '}')
        {
            oss << value;
            FormatLogImpl(oss, fmt + 2, std::forward<Args>(args)...);
            return;
        }
        oss << *fmt++;
    }
}

#else
// When building as part of AzerothCore, use the real Log.h
#include "Log.h"
#endif

#endif // _STANDALONE_LOG_H
