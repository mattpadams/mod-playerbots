/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license,
 * you may redistribute it and/or modify it under version 3 of the License, or (at your
 * option), any later version.
 */

#include "LlmBridgeHook.h"

#include "Log.h"
#include "PCQueue.h"
#include "PlayerbotAIConfig.h"

#include <boost/asio.hpp>
#include <chrono>
#include <sstream>
#include <string>
#include <thread>

using boost::asio::ip::tcp;

// -----------------------------------------------------------------------
// Static state
// -----------------------------------------------------------------------
std::string LlmBridgeHook::s_host;
std::string LlmBridgeHook::s_port;
std::string LlmBridgeHook::s_chatPath;
std::string LlmBridgeHook::s_lootRollPath;
bool        LlmBridgeHook::s_enabled = false;

// -----------------------------------------------------------------------
// Internal types
// -----------------------------------------------------------------------
struct HttpPostRequest
{
    std::string body;
    std::string path;   // empty → s_chatPath (back-compat)
};

static ProducerConsumerQueue<HttpPostRequest> s_queue;

static constexpr uint32_t MAX_QUEUE_SIZE = 1000;
static constexpr auto     HTTP_TIMEOUT   = std::chrono::seconds(5);

// -----------------------------------------------------------------------
// JSON helpers
// -----------------------------------------------------------------------
static std::string JsonEscape(std::string const& s)
{
    std::string out;
    out.reserve(s.size() + 8);
    for (char c : s)
    {
        switch (c)
        {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20)
                {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned char>(c));
                    out += buf;
                }
                else
                    out += c;
                break;
        }
    }
    return out;
}

// -----------------------------------------------------------------------
// URL parser  (expects "http://host:port/path")
// -----------------------------------------------------------------------
static bool ParseEndpoint(std::string const& url,
                          std::string& host, std::string& port, std::string& path)
{
    // Strip "http://"
    std::string remainder = url;
    if (remainder.substr(0, 7) == "http://")
        remainder = remainder.substr(7);
    else
        return false;  // only plain HTTP supported

    // Split host:port from path
    auto slashPos = remainder.find('/');
    std::string hostPort;
    if (slashPos != std::string::npos)
    {
        hostPort = remainder.substr(0, slashPos);
        path = remainder.substr(slashPos);
    }
    else
    {
        hostPort = remainder;
        path = "/";
    }

    // Split host and port
    auto colonPos = hostPort.find(':');
    if (colonPos != std::string::npos)
    {
        host = hostPort.substr(0, colonPos);
        port = hostPort.substr(colonPos + 1);
    }
    else
    {
        host = hostPort;
        port = "80";
    }

    return !host.empty();
}

// -----------------------------------------------------------------------
// Background worker — drains queue, sends HTTP POSTs
// -----------------------------------------------------------------------
void LlmBridgeWorkerLoop()
{
    LOG_INFO("playerbots", "LLM Bridge worker started ({}:{}{}).",
             LlmBridgeHook::s_host, LlmBridgeHook::s_port, LlmBridgeHook::s_chatPath);

    for (;;)
    {
        HttpPostRequest req;
        s_queue.WaitAndPop(req);

        // Empty body means the queue was shut down or cancelled
        if (req.body.empty())
            break;

        std::string const& path = req.path.empty()
            ? LlmBridgeHook::s_chatPath
            : req.path;

        try
        {
            tcp::iostream stream;
            stream.expires_after(HTTP_TIMEOUT);
            stream.connect(LlmBridgeHook::s_host, LlmBridgeHook::s_port);
            if (!stream)
            {
                LOG_ERROR("playerbots", "LLM Bridge: connect failed to {}:{}",
                          LlmBridgeHook::s_host, LlmBridgeHook::s_port);
                continue;
            }

            stream << "POST " << path << " HTTP/1.1\r\n";
            stream << "Host: " << LlmBridgeHook::s_host << ":" << LlmBridgeHook::s_port << "\r\n";
            stream << "Content-Type: application/json\r\n";
            stream << "Content-Length: " << req.body.size() << "\r\n";
            stream << "Connection: close\r\n";
            stream << "\r\n";
            stream << req.body;
            stream.flush();

            // Read status line (fire-and-forget, but log errors)
            std::string httpVersion;
            unsigned int statusCode = 0;
            stream >> httpVersion >> statusCode;

            if (statusCode < 200 || statusCode >= 300)
            {
                LOG_ERROR("playerbots", "LLM Bridge: POST returned HTTP {}", statusCode);
            }

            stream.close();
        }
        catch (std::exception const& e)
        {
            LOG_ERROR("playerbots", "LLM Bridge: POST failed — {}", e.what());
        }
    }

    LOG_INFO("playerbots", "LLM Bridge worker stopped.");
}

// -----------------------------------------------------------------------
// Public API
// -----------------------------------------------------------------------

void LlmBridgeHook::Init()
{
    std::string const& endpoint = sPlayerbotAIConfig.llmBridgeEndpoint;

    if (endpoint.empty())
    {
        s_enabled = false;
        return;
    }

    if (!ParseEndpoint(endpoint, s_host, s_port, s_chatPath))
    {
        LOG_ERROR("playerbots", "LLM Bridge: invalid endpoint URL '{}'. "
                  "Expected http://host:port/path", endpoint);
        s_enabled = false;
        return;
    }

    // Derive the loot-roll path by replacing the last segment of the
    // chat path (``/events/chat`` → ``/events/loot_roll``). If the path
    // doesn't match the expected shape, fall back to a sibling under
    // /events/.
    auto lastSlash = s_chatPath.find_last_of('/');
    if (lastSlash != std::string::npos)
        s_lootRollPath = s_chatPath.substr(0, lastSlash + 1) + "loot_roll";
    else
        s_lootRollPath = "/events/loot_roll";

    s_enabled = true;
    LOG_INFO("playerbots", "LLM Bridge enabled: {}", endpoint);

    std::thread worker(LlmBridgeWorkerLoop);
    worker.detach();
}

void LlmBridgeHook::Shutdown()
{
    if (!s_enabled)
        return;

    s_enabled = false;
    s_queue.Shutdown();
}

bool LlmBridgeHook::IsEnabled()
{
    return s_enabled;
}

void LlmBridgeHook::PostChatEvent(
    uint32_t botGuid,
    std::string const& botName,
    std::string const& senderName,
    std::string const& message,
    std::string const& channel)
{
    if (!s_enabled)
        return;

    // Backpressure: drop events if the queue is full
    if (s_queue.Size() >= MAX_QUEUE_SIZE)
    {
        LOG_WARN("playerbots", "LLM Bridge: queue full ({} events), dropping chat event",
                 MAX_QUEUE_SIZE);
        return;
    }

    std::ostringstream json;
    json << "{"
         << "\"bot_guid\":" << botGuid
         << ",\"bot_name\":\"" << JsonEscape(botName) << "\""
         << ",\"sender_name\":\"" << JsonEscape(senderName) << "\""
         << ",\"message\":\"" << JsonEscape(message) << "\""
         << ",\"channel\":\"" << JsonEscape(channel) << "\""
         << "}";

    s_queue.Push({json.str(), ""});
}

void LlmBridgeHook::PostLootRollEvent(
    std::string const& rollId,
    uint32_t itemId,
    std::string const& itemLink,
    std::string const& itemName,
    std::vector<uint32_t> const& candidateGuids)
{
    if (!s_enabled)
        return;

    if (s_queue.Size() >= MAX_QUEUE_SIZE)
    {
        LOG_WARN("playerbots", "LLM Bridge: queue full ({} events), dropping loot roll event",
                 MAX_QUEUE_SIZE);
        return;
    }

    std::ostringstream arr;
    arr << "[";
    for (size_t i = 0; i < candidateGuids.size(); ++i)
    {
        if (i)
            arr << ",";
        arr << candidateGuids[i];
    }
    arr << "]";

    std::ostringstream json;
    json << "{"
         << "\"roll_id\":\"" << JsonEscape(rollId) << "\""
         << ",\"item_id\":" << itemId
         << ",\"item_link\":\"" << JsonEscape(itemLink) << "\""
         << ",\"item_name\":\"" << JsonEscape(itemName) << "\""
         << ",\"candidate_guids\":" << arr.str()
         << "}";

    s_queue.Push({json.str(), s_lootRollPath});
}
