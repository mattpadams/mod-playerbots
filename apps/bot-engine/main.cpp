/*
 * Bot Engine - Standalone Process Entry Point
 *
 * Usage: bot-engine [options]
 *   --shm-name <name>    Shared memory name (default: swarm_bots)
 *   --tick-rate <hz>     AI tick rate in Hz (default: 20)
 *   --max-bots <n>       Max bots per tick (default: 1000)
 *   --help               Show this help
 */

#include "BotEngine.h"

#include <iostream>
#include <csignal>
#include <cstring>

namespace {
    botengine::BotEngine* g_engine = nullptr;

    void SignalHandler(int signal)
    {
        std::cout << "\n[BotEngine] Received signal " << signal << ", shutting down..." << std::endl;
        if (g_engine)
        {
            g_engine->RequestShutdown();
        }
    }

    void PrintHelp()
    {
        std::cout << "Bot Engine - Swarm Playerbots AI Process" << std::endl;
        std::cout << std::endl;
        std::cout << "Usage: bot-engine [options]" << std::endl;
        std::cout << std::endl;
        std::cout << "Options:" << std::endl;
        std::cout << "  --shm-name <name>    Shared memory name (default: swarm_bots)" << std::endl;
        std::cout << "  --tick-rate <hz>     AI tick rate in Hz (default: 20)" << std::endl;
        std::cout << "  --max-bots <n>       Max bots per tick (default: 1000)" << std::endl;
        std::cout << "  --help               Show this help" << std::endl;
        std::cout << std::endl;
    }

    void PrintBanner()
    {
        std::cout << "========================================" << std::endl;
        std::cout << "  Swarm Bot Engine v1.0" << std::endl;
        std::cout << "  Multi-process AI for Playerbots" << std::endl;
        std::cout << "========================================" << std::endl;
        std::cout << std::endl;
    }
}

int main(int argc, char* argv[])
{
    PrintBanner();

    // Parse arguments
    botengine::EngineConfig config;

    for (int i = 1; i < argc; ++i)
    {
        if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0)
        {
            PrintHelp();
            return 0;
        }
        else if (strcmp(argv[i], "--shm-name") == 0 && i + 1 < argc)
        {
            config.shmName = argv[++i];
        }
        else if (strcmp(argv[i], "--tick-rate") == 0 && i + 1 < argc)
        {
            config.tickRateHz = static_cast<uint32_t>(std::stoi(argv[++i]));
        }
        else if (strcmp(argv[i], "--max-bots") == 0 && i + 1 < argc)
        {
            config.maxBotsPerTick = static_cast<uint32_t>(std::stoi(argv[++i]));
        }
        else
        {
            std::cerr << "Unknown option: " << argv[i] << std::endl;
            PrintHelp();
            return 1;
        }
    }

    // Setup signal handlers
    signal(SIGINT, SignalHandler);
    signal(SIGTERM, SignalHandler);
#ifndef _WIN32
    signal(SIGHUP, SignalHandler);
#endif

    // Create and initialize engine
    botengine::BotEngine engine;
    g_engine = &engine;

    // Register example AI callback
    engine.RegisterAICallback([](botengine::LocalBotState& bot, float deltaTime)
    {
        // Example: Simple combat AI
        if (bot.combatFlags & 0x01)  // In combat
        {
            // If low health, try to heal/flee
            if (bot.health < bot.maxHealth / 4)
            {
                bot.aiState = 2;  // Flee state
            }
            else if (bot.targetGuid == 0)
            {
                bot.aiState = 1;  // Looking for target
            }
            else
            {
                bot.aiState = 3;  // Attacking
            }
        }
        else
        {
            bot.aiState = 0;  // Idle
        }

        // Update behavior timer
        if (bot.behaviorTimer > 0)
        {
            uint32_t deltaMs = static_cast<uint32_t>(deltaTime * 1000);
            bot.behaviorTimer = bot.behaviorTimer > deltaMs ? bot.behaviorTimer - deltaMs : 0;
        }
    });

    if (!engine.Initialize(config))
    {
        std::cerr << "[BotEngine] Initialization failed" << std::endl;
        return 1;
    }

    std::cout << "[BotEngine] Starting..." << std::endl;

    // Run main loop (blocks until shutdown)
    engine.Run();

    std::cout << "[BotEngine] Shutdown complete" << std::endl;
    std::cout << std::endl;
    std::cout << "Final Metrics:" << std::endl;
    const auto& metrics = engine.GetMetrics();
    std::cout << "  - Ticks Processed: " << metrics.ticksProcessed.load() << std::endl;
    std::cout << "  - Updates Received: " << metrics.updatesReceived.load() << std::endl;
    std::cout << "  - Actions Sent: " << metrics.actionsSent.load() << std::endl;
    std::cout << "  - Avg Tick Time: " << metrics.avgTickTimeUs.load() << " us" << std::endl;
    std::cout << "  - Max Tick Time: " << metrics.maxTickTimeUs.load() << " us" << std::endl;

    g_engine = nullptr;
    return 0;
}
