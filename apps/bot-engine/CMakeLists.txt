#
# Bot Engine - Standalone executable for multi-process bot AI
#
# Build separately from worldserver:
#   mkdir build && cd build
#   cmake ..
#   make
#

cmake_minimum_required(VERSION 3.16)
project(bot-engine)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Source files
set(BOT_ENGINE_SOURCES
    main.cpp
    BotEngine.cpp
    BotEngine.h
    SharedMemoryStandalone.cpp
    StandaloneLog.h
    ../../src/ecs/ipc/SharedMemory.h
    ../../src/ecs/ipc/IPC.h
)

# Create executable
add_executable(bot-engine ${BOT_ENGINE_SOURCES})

# Include directories
target_include_directories(bot-engine
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../../src/ecs/ipc
)

# Platform-specific linking
if(WIN32)
    # Windows doesn't need extra libs for shared memory
else()
    # POSIX shared memory requires rt library
    target_link_libraries(bot-engine PRIVATE rt pthread)
endif()

# Define standalone build flag
target_compile_definitions(bot-engine PRIVATE
    BOT_ENGINE_STANDALONE=1
)

# Install
install(TARGETS bot-engine DESTINATION bin)
