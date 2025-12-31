#
# mod-playerbots CMake Configuration
#
# This file is included by the main build system to add module-specific
# build targets and configurations.
#

# Option to build the standalone bot-engine
option(BUILD_BOT_ENGINE "Build the standalone bot-engine process" ON)

if(BUILD_BOT_ENGINE)
    message(STATUS "Building bot-engine standalone executable")

    # Source files for bot-engine
    set(BOT_ENGINE_SOURCES
        ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/apps/bot-engine/main.cpp
        ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/apps/bot-engine/BotEngine.cpp
        ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/apps/bot-engine/BotEngine.h
        ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/src/ecs/ipc/SharedMemory.cpp
        ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/src/ecs/ipc/SharedMemory.h
    )

    # Create bot-engine executable
    add_executable(bot-engine ${BOT_ENGINE_SOURCES})

    # Include directories
    target_include_directories(bot-engine
        PRIVATE
            ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/apps/bot-engine
            ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/src/ecs/ipc
            ${CMAKE_SOURCE_DIR}/modules/mod-playerbots/src/ecs
    )

    # Link against shared library (provides Log.h and other common utilities)
    target_link_libraries(bot-engine
        PRIVATE
            acore-core-interface
            shared
    )

    # Platform-specific
    if(UNIX AND NOT APPLE)
        target_link_libraries(bot-engine PRIVATE rt pthread)
    endif()

    # Set folder for IDE organization
    set_target_properties(bot-engine
        PROPERTIES
            FOLDER "modules/playerbots")

    # Install
    if(UNIX)
        install(TARGETS bot-engine DESTINATION bin)
    elseif(WIN32)
        install(TARGETS bot-engine DESTINATION "${CMAKE_INSTALL_PREFIX}")
    endif()

    message(STATUS "  +- bot-engine")
endif()
