/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license,
 * you may redistribute it and/or modify it under version 3 of the License, or (at your
 * option), any later version.
 */

#ifndef _PLAYERBOT_LLM_BRIDGE_HOOK_H
#define _PLAYERBOT_LLM_BRIDGE_HOOK_H

#include <cstdint>
#include <string>
#include <vector>

/// Fire-and-forget HTTP POST bridge to the Python LLM middleware.
///
/// A single background worker thread drains a lock-guarded queue and
/// sends each payload as an HTTP/1.1 POST over a raw TCP socket.
/// The world thread only does a Push(), which is effectively free.
///
/// Enabled when AiPlayerbot.LlmBridgeEndpoint is non-empty in the config.
class LlmBridgeHook
{
public:
    /// Parse the config value and start the background sender thread.
    static void Init();

    /// Signal the background thread to drain remaining items and exit.
    static void Shutdown();

    /// Returns true when a valid endpoint is configured.
    static bool IsEnabled();

    /// Enqueue a chat event for async delivery. Non-blocking.
    static void PostChatEvent(
        uint32_t botGuid,
        std::string const& botName,
        std::string const& senderName,
        std::string const& message,
        std::string const& channel);

    /// Enqueue a loot-roll-started event for middleware arbitration.
    /// Non-blocking; posts to ``/events/loot_roll``.
    /// ``candidateGuids`` is the list of party-member guids eligible
    /// for this roll. The middleware picks the best recipient and
    /// dispatches ``pass`` commands to the rest.
    static void PostLootRollEvent(
        std::string const& rollId,
        uint32_t itemId,
        std::string const& itemLink,
        std::string const& itemName,
        std::vector<uint32_t> const& candidateGuids);

private:
    static std::string s_host;
    static std::string s_port;
    static std::string s_chatPath;
    static std::string s_lootRollPath;
    static bool s_enabled;

    friend void LlmBridgeWorkerLoop();
};

#endif // _PLAYERBOT_LLM_BRIDGE_HOOK_H
