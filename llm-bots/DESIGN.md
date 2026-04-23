# AzerothCore LLM Bot System — Design Document

**Version:** 1.0
**Date:** 2026-04-13
**Status:** In Progress

## Milestone Progress

| # | Milestone | Status | Notes |
|---|-----------|--------|-------|
| 0 | Infrastructure & Connectivity | ✅ Complete | Committed `b930cb7bd` |
| 1 | Chat MVP | ✅ Complete | Committed `b930cb7bd` |
| 2 | Reactive Events (C++ Hook) | ✅ Complete | C++ rebuilt & deployed 2026-04-14; Python wake-on-push live |
| 3 | Combat Integration | ✅ Complete | EventPolicy registry, DebounceFilter, CombatContext, 5 raid tools, C++ `party,guid` TCP command — deployed 2026-04-14 |
| 4 | Questing, Trading, Full RPG | 🧪 Implemented, pending in-game test | PartyCoordinator (roster/quest/loot/arbitration/gear), 4 tool modules (party/quest/rpg/trade), `MANA_CRITICAL` event landed |
| 5 | Dungeon & Raid Coordination | 🧪 Implemented, pending in-game test | DungeonCoordinator, 80+ dungeon YAML profiles, `BOSS_PHASE_CHANGED` + `PARTY_MEMBER_DIED` + `ADDS_SPAWNED` events landed |
| 6 | Observability Dashboard | 🧪 Implemented, pending in-game test | Dashboard at `:8080`, SSE live feed, SQLite trace log, per-bot cost, Prometheus wired |
| 7 | Scale to 50+ Active Agents | 🧪 Implemented, pending in-game test | ProximityScanner, AutoElevator, DbClient pool, tick batching, rate-limit degradation |
| + | Admin Management | 🧪 Implemented, pending in-game test | `/admin` HTMX page, 7 v2 API routers, acore_llmbots DB, kill switch + per-player gating, PartyLogoffChecker |

**To fully activate M2 push flow**, set in `worldserver.conf`:
`AiPlayerbot.LlmBridgeEndpoint = "http://ac-bot-middleware:8180/events/chat"`

---

## Table of Contents

1. [Vision and Goals](#1-vision-and-goals)
2. [Architecture Overview](#2-architecture-overview)
3. [SDK Decision: Claude Agent SDK vs Anthropic API](#3-sdk-decision)
4. [Milestone 0: Infrastructure and Connectivity](#4-milestone-0)
5. [Milestone 1: Chat MVP](#5-milestone-1)
6. [Milestone 2: Reactive Events (C++ Hook)](#6-milestone-2)
7. [Milestone 3: Combat Integration](#7-milestone-3)
8. [Milestone 4: Questing, Trading, and Full RPG](#8-milestone-4)
9. [Milestone 5: Dungeon and Raid Coordination](#9-milestone-5)
10. [Milestone 6: Observability Dashboard](#10-milestone-6)
11. [Milestone 7: Scale to 50+ Active Agents](#11-milestone-7)
12. [Appendix A: Existing Bot Command Reference](#appendix-a)
13. [Appendix B: Personality Profile Schema](#appendix-b)
14. [Appendix C: Cost Projections](#appendix-c)

---

## 1. Vision and Goals

### What We Are Building

An AI layer that sits on top of AzerothCore's existing `mod-playerbots` module,
giving bots **personality**, **long-term memory**, and **intelligent behavior**
powered by Anthropic's Claude models. Bots will:

- Speak in-character across all chat channels and emotes
- Remember players, relationships, quest history, and combat lessons permanently
- Make strategic combat decisions (not spell-by-spell, but role and strategy)
- Accept, track, and complete quests with contextual reasoning
- Trade, group, and socialize like real players
- Coordinate in dungeons and raids with role-aware behavior
- Initiate conversations and react to their environment proactively

### What We Are NOT Building

- A replacement for mod-playerbots. The existing rule engine handles real-time
  combat execution (spell rotation, positioning, target switching). The LLM
  acts as a strategic "brain" that sets direction; the rule engine is the "body"
  that executes.
- A new game client or server. Zero changes to the core AzerothCore server.
  All integration is through mod-playerbots' existing interfaces.

### Scale Targets

| Metric | Target |
|--------|--------|
| Total bot characters | 200–500 |
| Active LLM agents simultaneously | 5–50 (configurable) |
| Remaining bots | Pure rule-engine (mod-playerbots default) |
| LLM response latency (chat) | < 3 seconds |
| LLM response latency (combat strategy) | < 5 seconds |
| Memory per bot | Unlimited (vector DB) |

---

## 2. Architecture Overview

### Container Layout

```
ac-network (Docker bridge)
+------------------------------------------------------------------+
|                                                                  |
|  ac-worldserver          ac-bot-middleware       ac-qdrant        |
|  (existing C++)          (Python 3.12)          (Vector DB)      |
|                                                                  |
|  Ports:                  Port: 8080             Port: 6333       |
|   8085 (game)            - FastAPI admin API    - Memory storage  |
|   7878 (SOAP)            - Agent supervisor     - Embeddings      |
|   8888 (bot TCP cmd)     - Cost controller                       |
|                          - LLM agents                            |
|  ac-database                                                     |
|  (MySQL 8.4)                                                     |
|  Port: 3306                                                      |
|                                                                  |
+------------------------------------------------------------------+
```

### Data Flow

```
Game Event                    Agent Decision                 Game Action
-----------                   ---------------                -----------
Player whispers bot      -->  Supervisor polls state    -->  Agent invokes LLM
Bot enters combat        -->  StateDiffer emits event   -->  LLM calls tools
Bot enters new zone      -->  Event routed to agent     -->  Tool calls CommandExecutor
Idle tick fires          -->  Agent builds context      -->  Executor sends TCP/SOAP cmd
                              (state + memories + personality)
                              LLM responds with tool calls
                              Memory manager stores interaction
```

### Integration Points with mod-playerbots

| Interface | Direction | Protocol | Used For |
|-----------|-----------|----------|----------|
| `PlayerbotCommandServer` (TCP :8888) | Read | `command,guid\n` | Querying bot state (hp, position, strategy, target) |
| `ExternalEventHelper::ParseChatCommand` | Write (via TCP) | `do <command>,guid\n` | Injecting chat commands that trigger bot actions |
| SOAP `:7878` | Write | XML/HTTP | GM-level commands, server admin |
| `POST /events/chat` (M2+) | Push | HTTP JSON | Real-time chat event notification from C++ hook |

### Key Existing Commands (via TCP `do` prefix)

These are the commands the LLM agent can inject into a bot:

**Chat:** `say <msg>`, `yell <msg>`, `whisper <name> <msg>`, `#p <msg>` (party),
`#r <msg>` (raid), `#g <msg>` (guild), `emote <name>`

**Combat/Strategy:** `co +<strategy>`, `co -<strategy>`, `attack <target>`,
`flee`, `stay`, `follow <player>`

**Quest:** `accept quest`, `drop`, `share`, `quests` (list)

**Trade:** `t <player> <item> [count]`

**Social:** `invite <player>`, `accept`, `leave`

**RPG:** `rpg status`, movement commands

---

## 3. SDK Decision

### Option A: Claude Agent SDK (`claude-agent-sdk`)

The official [Anthropic Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)
wraps Claude Code CLI and provides:

- `ClaudeSDKClient` for interactive multi-turn conversations
- `@tool` decorator for MCP-based tool definitions
- `create_sdk_mcp_server()` to register tools as an MCP server
- Hooks for intercepting tool calls (`PreToolUse`, `PostToolUse`)
- Built-in streaming, permission management, error handling

**Requires:** Claude Code CLI installed in the Docker container.

**Tool definition pattern:**
```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeSDKClient, ClaudeAgentOptions

@tool("say_in_chat", "Speak aloud in the game world", {"message": str})
async def say_in_chat(args):
    await executor.say(args["message"])
    return {"content": [{"type": "text", "text": f"Said: {args['message']}"}]}

server = create_sdk_mcp_server(name="game-tools", version="1.0.0", tools=[say_in_chat])

options = ClaudeAgentOptions(
    system_prompt=personality_prompt,
    mcp_servers={"game": server},
    allowed_tools=["mcp__game__say_in_chat", "mcp__game__emote", ...],
    max_turns=3,
)

async with ClaudeSDKClient(options=options) as client:
    await client.query(context_message)
    async for msg in client.receive_response():
        process(msg)
```

**Pros:** Full agent loop with tool orchestration, multi-turn reasoning, hooks.
**Cons:** Requires Claude Code CLI in Docker, heavier container, subprocess-based.

### Option B: Anthropic Python SDK (`anthropic`) with Tool Use

The standard [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
provides direct API access with tool use:

```python
import anthropic

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

tools = [
    {
        "name": "say_in_chat",
        "description": "Speak aloud in the game world",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]

response = await client.messages.create(
    model=model,
    system=personality_prompt,
    messages=[{"role": "user", "content": context_message}],
    tools=tools,
    max_tokens=512,
)

# Process tool_use blocks in response
for block in response.content:
    if block.type == "tool_use":
        await execute_tool(block.name, block.input)
```

**Pros:** Lightweight, no CLI dependency, full control over the agent loop,
direct token/cost tracking from response objects, simpler Docker container.
**Cons:** Must implement the agent loop (tool call → result → continue) manually.

### Decision: Claude Agent SDK (Option A)

**Use the Claude Agent SDK**, following the pattern proven by the
[AI-VTT Living Table](../AI-VTT/living-table/) project:

1. **No API key needed** — uses your Claude Pro/Max subscription via OAuth
   tokens from the host's Claude Code CLI (`~/.claude/.credentials.json`).
2. **Built-in agent loop** — the SDK handles tool call → result → continue
   automatically. No manual loop implementation.
3. **MCP-based tools** — tools are registered as an in-process MCP server,
   matching the Claude Code tool architecture.
4. **Provider abstraction** — tools use a provider-agnostic `@tool` decorator
   (`providers/tool_adapter.py`). The Claude provider re-wraps them for the
   SDK at query time. Swapping to raw API or another provider is one file.

**Auth pattern (from AI-VTT):**
- Run `claude login` on the host machine once
- Volume-mount `~/.claude/.credentials.json` into the container (read-only)
- `ClaudeAuthManager` loads the OAuth token and handles refresh
- The SDK's bundled CLI picks up the token via `CLAUDE_CODE_OAUTH_TOKEN` env var

**Docker volume mount:**
```yaml
volumes:
  - ${CLAUDE_CREDENTIALS_PATH:-~/.claude/.credentials.json}:/app/credentials.json:ro
  - ${CLAUDE_CREDENTIALS_PATH:-~/.claude/.credentials.json}:/home/botrunner/.claude/.credentials.json:ro
```

---

## 4. Milestone 0: Infrastructure and Connectivity

**Goal:** Docker stack running, Python service can talk to the game server.
**Duration estimate:** 1–2 days.
**C++ changes:** None.

### Tasks

#### 0.1 Docker Setup

- Create `llm-bots/docker-compose.override.yml` adding:
  - `ac-bot-middleware` (Python 3.12 + FastAPI)
  - `ac-qdrant` (Qdrant vector DB)
  - Both on `ac-network`
- Create `llm-bots/.env` from `.env.example` with real API key
- Verify `commandServerPort` is set in `playerbots.conf` (default: 8888)
- Verify SOAP is enabled in `worldserver.conf` (`SOAP.Enabled = 1`, port 7878)

**Files:**
```
llm-bots/docker-compose.override.yml    (created)
llm-bots/.env.example                   (created)
llm-bots/middleware/Dockerfile           (created)
llm-bots/middleware/pyproject.toml       (created)
```

#### 0.2 TCP Connectivity Test

- Start the Docker stack: `docker compose -f docker-compose.yml -f llm-bots/docker-compose.override.yml up -d`
- From the middleware container, connect to `ac-worldserver:8888`
- Send `state,<known_bot_guid>\n` and verify a response
- Send `position,<guid>\n`, `hp,<guid>\n`, `strategy,<guid>\n`

**Validation script** (run inside middleware container):
```python
import asyncio

async def test():
    reader, writer = await asyncio.open_connection("ac-worldserver", 8888)
    writer.write(b"state,1234\n")  # replace 1234 with real bot guid
    await writer.drain()
    line = await reader.readline()
    print(f"State: {line.decode().strip()}")
    writer.close()

asyncio.run(test())
```

#### 0.3 SOAP Connectivity Test

- Send a `server info` command via SOAP to verify authentication works
- Test with: `curl -u admin:admin -H "Content-Type: text/xml" -d '<SOAP-ENV:Envelope ...><ns1:executeCommand><command>server info</command>...' http://ac-worldserver:7878/`

#### 0.4 Qdrant Connectivity Test

- Verify Qdrant is healthy: `curl http://ac-qdrant:6333/healthz`
- Create a test collection, insert a vector, query it, delete it

### Success Criteria

- [x] `docker compose up` starts all 4 containers (worldserver, database, middleware, qdrant)
- [x] TCP query returns valid bot state from middleware container
- [x] SOAP command executes successfully
- [x] Qdrant health check passes
- [x] FastAPI health endpoint returns 200 at `http://localhost:8080/health`

---

## 5. Milestone 1: Chat MVP

**Goal:** One bot can hold in-character conversations with players, remember
interactions, and respond with personality.
**Duration estimate:** 3–5 days.
**C++ changes:** None.
**Depends on:** Milestone 0.

### Architecture for M1

```
Player whispers bot
        |
        v
[Supervisor poll loop, every 3s]
        |
  polls TCP "action,guid" and "state,guid"
        |
  StateDiffer detects new chat-related action
        |
  Emits ChatReceivedEvent (inferred from state change)
        |
  BotAgent.handle_event()
        |
  builds context: state + memories + personality
        |
  calls anthropic.messages.create() with tools
        |
  LLM responds with say() or whisper() tool call
        |
  CommandExecutor sends "do say <msg>,guid" via TCP
        |
  Bot speaks in game
        |
  MemoryManager stores the interaction in Qdrant
```

### Tasks

#### 1.1 Core Infrastructure (already built)

These files are already implemented:

| File | Purpose |
|------|---------|
| `core/config.py` | Pydantic settings from env vars |
| `core/game_client.py` | TCP connection pool to PlayerbotCommandServer |
| `core/soap_client.py` | SOAP client for GM commands |
| `core/event_bus.py` | Per-bot async event queues |
| `core/bot_registry.py` | Tracks elevated vs rule-engine bots |
| `core/command_executor.py` | Translates BotCommand → TCP/SOAP calls |
| `game/events.py` | Typed event models |
| `game/commands.py` | Typed command models |
| `game/state_differ.py` | Generates events from state snapshot diffs |

#### 1.2 Update Agent to Use Raw Anthropic SDK

The current `bot_agents/bot_agent.py` imports `agents` (the OpenAI SDK) which
is wrong. Refactor to use the `anthropic` SDK directly:

```python
import anthropic

class BotAgent:
    def __init__(self, ...):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._tools = self._build_tool_definitions()

    async def _run_agent_loop(self, context_msg: str, model: str) -> AgentTrace:
        messages = [{"role": "user", "content": context_msg}]
        trace = AgentTrace(...)

        while True:
            response = await self._client.messages.create(
                model=model,
                system=self._system_prompt,
                messages=messages,
                tools=self._tools,
                max_tokens=512,
            )
            trace.tokens_in += response.usage.input_tokens
            trace.tokens_out += response.usage.output_tokens

            # Check if we need to process tool calls
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                # Agent is done — extract final text response
                for block in response.content:
                    if block.type == "text":
                        trace.response_preview = block.text[:200]
                break

            # Execute tool calls and build results
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_use in tool_uses:
                result = await self._execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
                trace.tool_calls.append(tool_use.name)
            messages.append({"role": "user", "content": tool_results})

            # Safety: max 5 tool rounds per invocation
            if len(trace.tool_calls) >= 5:
                break

        return trace
```

**Tool definitions** become standard Anthropic tool schema dicts:
```python
def _build_tool_definitions(self) -> list[dict]:
    return [
        {
            "name": "say",
            "description": "Speak aloud so nearby players can hear you.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "What to say"}
                },
                "required": ["message"],
            },
        },
        {
            "name": "whisper",
            "description": "Send a private message to a specific player.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_player": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["target_player", "message"],
            },
        },
        {
            "name": "emote",
            "description": "Perform an emote. Available: wave, bow, laugh, cry, dance, cheer, sit, kneel, point, roar, salute, flex, shrug, clap, thank, beg.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "emote_name": {"type": "string"}
                },
                "required": ["emote_name"],
            },
        },
        {
            "name": "remember_this",
            "description": "Store something important to your long-term memory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "memory_type": {
                        "type": "string",
                        "enum": ["conversation", "relationship", "world_event", "personality"],
                    },
                },
                "required": ["content"],
            },
        },
        {
            "name": "recall",
            "description": "Search your memory for information about a topic or player.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"],
            },
        },
    ]
```

#### 1.3 Chat Detection via Polling

The TCP command server is **read-only** — it cannot push events. For M1, we
detect chat events by polling the `action` field and watching for chat-related
action names.

**Known chat action names** from mod-playerbots:
- `chat reply` — bot received and processed incoming chat
- `say` — bot is saying something
- `reply` — bot replied to a message

The `StateDiffer` already compares `last_action` between snapshots. When it
changes to a chat-related action, it emits an `ActionChangedEvent`.

**Enhancement for M1:** Add a heuristic in the supervisor that treats
`action == "chat reply"` as a signal that someone spoke to the bot. The
existing rule engine's reply will fire first (if enabled), but the LLM agent
will also trigger.

**Important:** To prevent the existing rule engine's `ChatReplyAction` from
interfering with LLM responses, bots elevated to LLM mode should have the
`chat` strategy removed: `co -chat`. This is done automatically when a bot
is elevated via the admin API.

#### 1.4 Personality System

Already built. Five YAML profiles:
- `base.yaml` — default template
- `gruff_warrior.yaml` — terse dwarven tank
- `cheerful_healer.yaml` — optimistic draenei priest
- `mysterious_mage.yaml` — cryptic blood elf arcanist
- `cynical_rogue.yaml` — sarcastic undead merchant

**System prompt structure:**
```
You are {name}, a {race} {class} in Azeroth.

BACKSTORY: ...
PERSONALITY TRAITS: ...
SPEECH PATTERNS: ...

RULES:
- Stay in character at all times
- NEVER reveal you are AI
- NEVER use modern slang
- Keep responses concise (game chat, not a novel)
- Use tools to take actions
```

#### 1.5 Memory System

Already built. Uses Qdrant with `all-MiniLM-L6-v2` local embeddings (384-dim).

**M1 memory operations:**
- Store every chat interaction (importance 0.8)
- Retrieve top-5 memories by semantic similarity before each LLM call
- Multi-query RRF: situational + player-specific + personality anchors
- `remember_this` tool lets the LLM explicitly store facts

#### 1.6 Admin API for Elevation

Already built. Key endpoints:

```
POST /admin/bots/{guid}/elevate   {"name": "Thaldrin", "personality": "gruff_warrior"}
POST /admin/bots/{guid}/demote
GET  /admin/bots
GET  /admin/bots/{guid}/memories
DELETE /admin/bots/{guid}/memories
GET  /admin/cost
```

### Testing Plan for M1

1. Start all containers
2. Log into the WoW game client
3. Identify a random bot's GUID from the database
4. Elevate it: `curl -X POST http://localhost:8080/admin/bots/1234/elevate -d '{"name":"Thaldrin","personality":"gruff_warrior"}'`
5. Find the bot in-game and whisper it: `/w Thaldrin Hello there!`
6. Wait 3-6 seconds (poll interval + LLM latency)
7. Observe: bot should respond in-character as a gruff dwarven warrior
8. Whisper again referencing a previous topic — verify memory recall
9. Check traces: `curl http://localhost:8080/admin/traces`
10. Check cost: `curl http://localhost:8080/admin/cost`

### Success Criteria

- [x] Bot responds in-character within 5 seconds of receiving a whisper
- [x] Response matches personality profile (tone, vocabulary, backstory)
- [x] Bot remembers previous conversation in the same session
- [x] Bot uses emotes naturally during conversation
- [x] Cost tracking shows accurate token counts
- [x] Demoting a bot returns it to rule-engine behavior immediately

---

## 6. Milestone 2: Reactive Events (C++ Hook)

**Goal:** Eliminate polling latency for chat events. When a player speaks to a
bot, the game server immediately notifies the middleware via HTTP POST.
**Duration estimate:** 2–3 days.
**C++ changes:** ~50 lines in one new file + one line in an existing file.
**Depends on:** Milestone 1.

### The Problem

In M1, the supervisor polls every 3 seconds. In the worst case, a player
whispers a bot and waits up to 3s (poll) + 3s (LLM) = 6 seconds for a reply.
For chat, this feels sluggish.

### The Solution

Add a lightweight HTTP POST hook in the C++ bot code that fires when an
LLM-elevated bot receives incoming chat. The hook is fire-and-forget — it
POSTs a JSON payload to `http://ac-bot-middleware:8080/events/chat` and
does not wait for a response.

### C++ Implementation

#### New file: `modules/mod-playerbots/src/LLM/LlmBridgeHook.h`

```cpp
#ifndef _PLAYERBOT_LLM_BRIDGE_HOOK_H
#define _PLAYERBOT_LLM_BRIDGE_HOOK_H

#include <string>
#include <cstdint>

class LlmBridgeHook
{
public:
    // Post a chat event to the Python middleware.
    // Non-blocking: fires HTTP POST in a detached thread.
    static void PostChatEvent(
        uint32 botGuid,
        std::string const& botName,
        std::string const& senderName,
        std::string const& message,
        std::string const& channel
    );

    // Check if the bridge is enabled (config setting)
    static bool IsEnabled();

    // Initialize from config
    static void Init();

private:
    static std::string s_endpoint;  // "http://ac-bot-middleware:8080/events/chat"
    static bool s_enabled;
};

#endif
```

#### New file: `modules/mod-playerbots/src/LLM/LlmBridgeHook.cpp`

```cpp
#include "LlmBridgeHook.h"
#include "PlayerbotAIConfig.h"
#include "Log.h"
#include <thread>
#include <sstream>

// Using Boost.Beast or a simple raw HTTP POST.
// For simplicity, use a raw socket POST (no external deps).
#include <boost/asio.hpp>

std::string LlmBridgeHook::s_endpoint = "";
bool LlmBridgeHook::s_enabled = false;

void LlmBridgeHook::Init()
{
    // Read from playerbots.conf: AiPlayerbot.LlmBridgeEndpoint
    s_endpoint = sPlayerbotAIConfig.GetStringDefault(
        "AiPlayerbot.LlmBridgeEndpoint", "");
    s_enabled = !s_endpoint.empty();
    if (s_enabled)
        LOG_INFO("playerbots", "LLM Bridge enabled: {}", s_endpoint);
}

bool LlmBridgeHook::IsEnabled() { return s_enabled; }

void LlmBridgeHook::PostChatEvent(
    uint32 botGuid,
    std::string const& botName,
    std::string const& senderName,
    std::string const& message,
    std::string const& channel)
{
    if (!s_enabled) return;

    // Fire-and-forget in a detached thread to avoid blocking the world thread
    std::thread([=]() {
        try {
            // Build JSON payload
            std::ostringstream json;
            json << "{\"bot_guid\":" << botGuid
                 << ",\"bot_name\":\"" << botName << "\""
                 << ",\"sender_name\":\"" << senderName << "\""
                 << ",\"message\":\"" << message << "\""  // TODO: escape quotes
                 << ",\"channel\":\"" << channel << "\"}";

            // Parse endpoint URL (assume http://host:port/path)
            // ... HTTP POST using Boost.Asio (omitted for brevity) ...

        } catch (...) {
            // Silently ignore — the game must never crash due to LLM bridge
        }
    }).detach();
}
```

#### Hook insertion point

In `PlayerbotAI.cpp`, inside the `HandleCommand` method where incoming
chat is processed, add a single call:

```cpp
// After existing chat handling logic:
if (LlmBridgeHook::IsEnabled())
{
    LlmBridgeHook::PostChatEvent(
        bot->GetGUID().GetCounter(),
        bot->GetName(),
        fromPlayer->GetName(),
        text,
        channelName
    );
}
```

#### Config addition

In `playerbots.conf.dist`:
```ini
# LLM Bridge endpoint for real-time event push to the Python middleware.
# Leave empty to disable. Example: http://ac-bot-middleware:8080/events/chat
AiPlayerbot.LlmBridgeEndpoint = ""
```

### Python Side

The endpoint `POST /events/chat` already exists in `api/events.py`. It
receives the JSON payload, creates a `ChatReceivedEvent`, and publishes it
to the bot's `EventBus` queue. The supervisor picks it up on the next tick
(or immediately if the agent is waiting on `event_bus.consume()`).

### Latency Improvement

| Scenario | M1 (polling) | M2 (push) |
|----------|-------------|-----------|
| Player whispers bot | 0–3s poll + 1–3s LLM = 1–6s | ~50ms push + 1–3s LLM = 1–3s |
| Player says nearby | 0–3s poll + 1–3s LLM = 1–6s | ~50ms push + 1–3s LLM = 1–3s |

### Success Criteria

- [x] Chat events arrive at the middleware within 100ms of being sent in-game
- [x] Bot responds to whispers within 3 seconds consistently
- [x] The C++ hook does not impact game server performance (detached thread + bounded queue)
- [x] Disabling the config setting (`LlmBridgeEndpoint = ""`) fully disables the hook
- [x] Polling continues to work as a fallback for non-chat events

### M2 Implementation Notes

- **C++ side**: `LlmBridgeHook` fire-and-forget HTTP POST with background worker thread and
  1000-item bounded queue. Integrated in `Playerbots.cpp` for whisper/party/raid/guild chat.
  `WORLDHOOK_ON_SHUTDOWN` calls `LlmBridgeHook::Shutdown()` to drain cleanly.
- **Python side**: `EventBus` exposes an `asyncio.Event` wake flag set on every `publish()`.
  The supervisor replaced `asyncio.sleep(tick_interval)` with `asyncio.wait({wake, stop, timer},
  FIRST_COMPLETED)` so push events wake it immediately instead of waiting the full 3s poll.
- **Deferred**: say/yell hooks. These bypass `OnPlayerCanUseChat` in AzerothCore's core
  chat handler and would require spatial queries for nearby bots — not in M2 scope.
- **Tests**: `tests/test_m2_reactive_events.py` — 6 tests, all passing (covers wake
  flag, endpoint publishing, and supervisor early-wake integration).

---

## 7. Milestone 3: Combat Integration

**Goal:** Bots make intelligent strategic decisions when entering combat. The
LLM chooses role, strategy, and high-level tactics; the rule engine handles
real-time spell rotation.
**Duration estimate:** 5–7 days.
**C++ changes:** None (uses existing `co` strategy change commands).
**Depends on:** Milestone 1.

### Hybrid Combat Model

```
                    LLM (strategic, 1 call per fight)
                    +-----------------------------------------+
                    | "Tank is taking heavy damage.            |
                    |  Switch to healing focus.                |
                    |  Call out to DPS to focus the adds."     |
                    +-----------------------------------------+
                              |                    |
                    change_strategy("+heal")    party_chat("Focus the adds!")
                              |                    |
                              v                    v
                    Rule Engine (tactical, every 250ms)
                    +-----------------------------------------+
                    | Cast Greater Heal on tank                |
                    | Renew on tank                            |
                    | Prayer of Mending on tank                |
                    | (all handled by existing heal strategy)  |
                    +-----------------------------------------+
```

### New Tools for M3

```python
combat_tools = [
    {
        "name": "change_strategy",
        "description": (
            "Change your combat behavior. Use + to add strategies, - to remove. "
            "Available strategies: tank assist, dps assist, heal, "
            "ranged, close (melee), flee, passive, aggressive, "
            "pull, aoe, cc (crowd control). "
            "Examples: '+heal', '-ranged,+close', '+tank assist,+aoe'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strategy_change": {
                    "type": "string",
                    "description": "Strategy change expression (e.g., '+heal,-dps assist')"
                }
            },
            "required": ["strategy_change"],
        },
    },
    {
        "name": "set_focus_target",
        "description": "Tell your group to focus a specific enemy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string"}
            },
            "required": ["target_name"],
        },
    },
    {
        "name": "flee",
        "description": "Run away from combat. Use when the fight is unwinnable.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "follow_player",
        "description": "Follow a player closely during combat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string"}
            },
            "required": ["player_name"],
        },
    },
]
```

### Combat Context Window

When combat starts, the LLM receives:

```
[CURRENT STATE]
You are Thaldrin, a level 80 dwarf warrior (Protection spec) in Icecrown.
Health: 85%. Status: combat.
Target: Skeletal Warrior (hp: 60%)
Active strategy: tank assist, close

[PARTY]
- Elariel (Priest, Holy) — hp: 92%, healing you
- Shadowstep (Rogue, Combat) — hp: 78%, attacking Skeletal Warrior
- Frostweave (Mage, Frost) — hp: 95%, casting Blizzard

[ENEMIES]
- Skeletal Warrior (your target, hp: 60%)
- Skeletal Archer (hp: 100%, targeting Frostweave)
- Plague Ghoul (hp: 100%, targeting Elariel)

[RECENT EVENTS]
- Combat started with Skeletal Warrior
- Skeletal Archer is attacking Frostweave
- Plague Ghoul is attacking Elariel

[RELEVANT MEMORIES]
- Elariel panics when enemies attack her directly
- Last time we fought undead, AOE worked best

[WHAT JUST HAPPENED]
Combat started with Skeletal Warrior
```

### Combat Decision Rules

1. **One LLM call per combat encounter** (on `CombatStartEvent`)
2. **Additional call if health drops below 20%** (on `HealthCriticalEvent`)
3. **No LLM calls during routine combat** — rule engine handles it
4. **Party/raid chat during combat is allowed** (LLM can call out targets)
5. **Strategy changes take effect on the next rule-engine tick** (~250ms)

### State Enrichment for Combat

To give the LLM party and enemy information, we need to extend the TCP
queries. The existing `values` command returns all AI context values, but
it's a raw debug dump. For M3, parse the `values` output to extract:

- `party member count`, `party member names`
- `nearest enemy count`, `attacker count`
- `aoe count` (enemies in AOE range)

Alternatively, add new SQL queries to read party composition from
`acore_characters.group_member` directly from Python.

### Success Criteria

- [x] Bot calls `change_strategy` appropriately when combat starts
- [x] Bot uses `party_chat` to coordinate with group members
- [x] Bot calls `flee` when health is critical and fight is unwinnable
- [x] Rule engine continues handling spell rotation smoothly
- [x] LLM is NOT called on every combat tick (only at start + critical health, with 30s cooldown)
- [x] Strategy changes are contextually appropriate (e.g., healer switches to heal focus)

### M3 Implementation Notes

**Architecture** — introduced three reusable abstractions that pay off in M4-M7:

- `game/event_policy.py` — `EventPolicy` dataclass + `POLICY_REGISTRY` as the
  single source of truth for "does this event trigger an LLM call, at what
  priority, with which model tier, and does it need combat context?" Replaces
  scattered if-chains in `BotAgent._should_invoke_llm`, the supervisor's
  `_pick_best_event` priority dict, and `CostController._IMPORTANT_EVENTS` set.
  Adding a new event type for M4-M7 is one registry entry.
- `game/debounce.py` — per-bot `DebounceFilter` sits between `state_differ.diff()`
  and the event queue. Reads `EventPolicy.cooldown_seconds`. Created/destroyed
  with each `BotAgent` in the supervisor.
- `combat/` package — `CombatContextBuilder` fetches party composition + enemy
  state via TCP queries, but only when a policy's `needs_combat_context=True`
  (currently `COMBAT_START` and `HEALTH_CRITICAL`). Heavy queries stay off the
  3-second polling path.

**Raid tools** (`bot_agents/tools/raid_tools.py`) — 5 new tools composed over
existing `PARTY_CHAT` / `EXECUTE_ACTION` / `SET_STRATEGY` commands, no new
`CommandType` enums needed:

- `focus_target` — party-chat callout + `+dps assist` strategy
- `mark_target` — raid marker icon (skull/cross/etc.) + party-chat announcement
- `assist_player` — target whoever a player is targeting (uses `assist <name>`)
- `request_heal` — three urgency levels, formatted party-chat call for heals
- `call_out_mechanic` — party-chat warning for boss mechanics (capped at 100 chars)

**C++ side** (`modules/mod-playerbots/src/Bot/PlayerbotAI.cpp`) — added one new
TCP command `party,guid` returning pipe-delimited `Name:Class:HpPct`. Returns
empty string when solo. Also fixed a latent upstream bug in
`Value.cpp:Uint8CalculatedValue::Format()` where `out << uint8(n)` was emitting
a raw byte instead of a decimal string (affected `attacker count`,
`my attacker count`, `balance percentage`, and every other `Uint8CalculatedValue`).

**Decisions** —

- **No "one LLM call per combat" hard guard.** Raids have phases and can last
  10+ minutes; the rate limiter (6 calls/min/bot) + 30s `HEALTH_CRITICAL`
  cooldown is the ceiling. `COMBAT_START` fires every time combat begins, and
  can fire again within the same fight if target or state transitions restart it.
- **No HP re-arm gate for `HEALTH_CRITICAL`.** An earlier design required HP to
  recover above 40% before re-firing. Dropped because the differ only fires on
  threshold *crossings* anyway — if HP stays below 20%, there's no duplicate to
  debounce. Cooldown alone is sufficient and doesn't silence legitimate
  re-evaluations during long fights.
- **`_idle_counter` encapsulation fix** — M1 had the supervisor mutating
  `BotAgent._idle_counter` directly. Fixed as part of M3 polish via a new
  `BotAgent.maybe_emit_idle()` method that owns both the counter and the event
  emission.
- **Graceful degradation** — `CombatContextBuilder` tolerates failure of either
  TCP query; missing data just means the `[COMBAT SITUATION]` prompt block is
  smaller. The system still functions if the worldserver is rolled back to a
  build without the `party,guid` command.

**Deferred (tracked for future milestones)** —

- `MANA_CRITICAL` event + detection → **M4** (resource management)
- `PARTY_MEMBER_DIED` event → **M5** (raid/dungeon coordination)
- `ADDS_SPAWNED` event → **M5** (boss encounter awareness)
- `BOSS_PHASE_CHANGED` event → **M5** (dungeon scope per design doc)
- `TARGET_HEALTH_CRITICAL` event → **M5** or ad-hoc follow-up
- `COMBAT_END` LLM call → **M4** (post-combat "what next" decisions)

**Tests** — `tests/test_m3_combat.py`: 38 tests covering policy registry, debounce
cooldown + regression guard, parser edge cases (malformed, raw-byte uint8,
singular/plural attacker-count key variants), prompt rendering, raid tool
dispatch, and `maybe_emit_idle` lifecycle. Combined suite: 44 passing
(38 M3 + 6 M2).

---

## 8. Milestone 4: Questing, Trading, and Full RPG

**Goal:** Bots can accept quests, trade items, and engage in full RPG behavior
with contextual reasoning about what to do next.
**Duration estimate:** 7–10 days.
**C++ changes:** None.
**Depends on:** Milestone 3.

### New Tools for M4

```python
quest_tools = [
    {
        "name": "accept_quest",
        "description": "Accept a quest from a nearby quest giver.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quest_name_or_id": {"type": "string"}
            },
            "required": ["quest_name_or_id"],
        },
    },
    {
        "name": "drop_quest",
        "description": "Abandon a quest from your quest log.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quest_name_or_id": {"type": "string"}
            },
            "required": ["quest_name_or_id"],
        },
    },
    {
        "name": "list_quests",
        "description": "List all quests in your quest log with their status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "share_quest",
        "description": "Share a quest with your party members.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quest_name_or_id": {"type": "string"}
            },
            "required": ["quest_name_or_id"],
        },
    },
]

trade_tools = [
    {
        "name": "trade_item",
        "description": "Initiate a trade with a player, offering an item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string"},
                "item_name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
            },
            "required": ["player_name", "item_name"],
        },
    },
    {
        "name": "buy_from_vendor",
        "description": "Buy an item from a nearby vendor NPC.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "sell_to_vendor",
        "description": "Sell an item to a nearby vendor NPC.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string"}
            },
            "required": ["item_name"],
        },
    },
]

rpg_tools = [
    {
        "name": "set_rpg_mode",
        "description": (
            "Change your RPG behavior mode. Options: "
            "grind (kill mobs), travel (move to a destination), "
            "quest (focus on quests), rest (sit and recover), "
            "idle (stand around), explore (wander)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["grind", "travel", "quest", "rest", "idle", "explore"]
                }
            },
            "required": ["mode"],
        },
    },
    {
        "name": "go_to_location",
        "description": "Travel to a named location or coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {"type": "string", "description": "Zone name or 'x y z' coordinates"}
            },
            "required": ["destination"],
        },
    },
]
```

### RPG Decision Loop

Unlike chat (reactive) or combat (one-shot), RPG behavior is **proactive**.
The bot decides what to do when idle:

```
[Idle tick fires every ~30 seconds for idle bots]
        |
  BotAgent receives IdleTickEvent
        |
  LLM evaluates: "What should I do next?"
        |
  Context includes: current quests, location, nearby NPCs,
                    recent events, personality goals
        |
  LLM decides: "I should turn in the quest I completed"
        |
  Calls go_to_location("quest giver") + accept_quest(...)
```

### Proactive Behavior Engine

Add a `proactive_engine.py` to the scheduler:

```python
class ProactiveEngine:
    def should_initiate(self, agent: BotAgent, snapshot: BotSnapshot) -> bool:
        """Decide if this bot should proactively do something."""
        profile = agent._profile
        personality = load_profile(profile.personality)
        threshold = personality.get("response_style", {}).get("initiation_threshold", 0.5)

        # Factors that increase initiative:
        # - Player nearby (within 30 yards)
        # - Bot has been idle for a while
        # - Bot is in an interesting location
        # - Personality has high initiation_threshold

        idle_time = time.monotonic() - agent._last_action_time
        idle_factor = min(idle_time / 60.0, 1.0)  # caps at 1 minute

        return random.random() < (threshold * idle_factor)
```

### Quest Tracking via Memory

When a bot accepts a quest, store it as a high-importance memory:
```
"Accepted quest 'The Legend of Stalvan' from Clerk Daltry in Darkshire.
Objective: Find the Stalvan letters."
```

When the bot completes an objective, update memory:
```
"Found the first Stalvan letter in the Darkshire town hall."
```

This lets the LLM reason about quest progress naturally through memory
retrieval rather than requiring a separate quest tracking system.

### Success Criteria

- [ ] Bot can accept a quest when a player says "let's do this quest"
- [ ] Bot shares quests with party members
- [ ] Bot trades items when asked by a player
- [ ] Bot decides what to do when idle (grind, quest, explore) based on personality
- [ ] Bot remembers quest progress across sessions
- [ ] Bot can navigate to quest objectives
- [ ] Trading respects personality (cynical rogue haggles, cheerful healer gives freely)

---

## 9. Milestone 5: Dungeon and Raid Coordination

**Goal:** Bots can participate in 5-man dungeons and raids with role-aware
behavior, boss mechanic awareness, and group coordination.
**Duration estimate:** 10–14 days.
**C++ changes:** None (uses existing dungeon strategies in mod-playerbots).
**Depends on:** Milestone 3, Milestone 4.

### Dungeon Architecture

```
Party enters dungeon
        |
  Supervisor detects zone change to instance
        |
  All party bots switch to DUNGEON mode
        |
  LLM receives dungeon-specific system prompt addendum:
        |
  "You are in Utgarde Keep. Boss order: Keleseth → Skarvald → Ingvar.
   Your role: Tank. Stay ahead of the group, pull carefully."
        |
  LLM sets strategy: "+tank assist,+pull"
        |
  Before each boss, LLM is called with boss-specific context:
        |
  "Next boss: Prince Keleseth. He summons Frost Tombs that trap players.
   As tank, position him away from the group. If a party member gets
   Frost Tombed, call out to DPS to break the tomb."
```

### Dungeon Context Database

Create a YAML knowledge base of dungeon/boss mechanics:

```yaml
# personality/dungeons/utgarde_keep.yaml
name: "Utgarde Keep"
instance_id: 574
bosses:
  - name: "Prince Keleseth"
    order: 1
    mechanics:
      - "Summons Frost Tombs that trap players — DPS must break them"
      - "Shadow Bolts on the tank — healers watch tank health"
    tank_instructions: "Face him away from group. Taunt adds."
    healer_instructions: "Heavy tank damage during Shadow Bolts. Dispel frost."
    dps_instructions: "Priority: break Frost Tombs immediately, then boss."

  - name: "Skarvald & Dalronn"
    order: 2
    mechanics:
      - "Kill Skarvald first (melee), then Dalronn (caster)"
      - "Dalronn's ghost persists after death — ignore ghost, kill Skarvald"
    tank_instructions: "Tank Skarvald. Dalronn can be interrupted."
    healer_instructions: "AoE healing during Skarvald's charge."
    dps_instructions: "Focus Skarvald, interrupt Dalronn's Shadow Bolts."

  - name: "Ingvar the Plunderer"
    order: 3
    mechanics:
      - "Phase 1: Smash (frontal cone) — dodge if you're not the tank"
      - "Phase 2: Dark Smash, Shadow Axe — more damage, same mechanics"
    tank_instructions: "Face him away. Don't move during Smash."
    healer_instructions: "Heavy damage in Phase 2. Save cooldowns."
    dps_instructions: "Stay behind him. Move out of Dark Smash."
```

### Role-Aware System Prompt Addendum

When a bot enters a dungeon, append to the system prompt:

```
DUNGEON MODE: You are in {dungeon_name}.
Your role: {tank|healer|dps}
Boss order: {boss1} → {boss2} → {boss3}

Current boss: {boss_name}
Your instructions: {role_specific_instructions}

RULES IN DUNGEONS:
- Follow the tank's lead (if you're not the tank)
- Call out important mechanics in party chat
- Use change_strategy to adapt to boss phases
- If you die, wait for a resurrection before acting
```

### Party Leader Agent

One bot per party can be designated as "leader" via personality config:

```yaml
# personality config
dungeon_role: "leader"
```

The leader bot:
- Decides pull timing ("Ready? Pulling in 3...")
- Calls out boss mechanics ("Frost Tomb on Elariel! Break it!")
- Coordinates CC ("Sheep the caster, I'll pull the rest")
- Decides when to retreat ("Wipe it, run to entrance")

Non-leader bots respond to leader callouts via party chat context.

### Existing Dungeon Strategy Integration

mod-playerbots already has per-dungeon strategies with boss-specific triggers:

```cpp
// Example: Utgarde Keep has triggers for:
"keleseth frost tomb"    → attack frost tomb
"dalronn priority"       → attack dalronn first
"ingvar smash tank"      → dodge frontal cone
```

The LLM doesn't need to replicate these — it just needs to activate the
right dungeon strategy:

```python
# When entering Utgarde Keep:
await command_executor.execute(BotCommand(
    command_type=CommandType.SET_STRATEGY,
    payload={"strategy": "+wotlk-uk"}  # activates Utgarde Keep strategy
))
```

The LLM adds the **social** layer on top: calling out mechanics, encouraging
the group, reacting to wipes, adjusting strategy if the default fails.

### Supported Dungeons (mod-playerbots has strategies for)

| Dungeon | Strategy Key | Status |
|---------|-------------|--------|
| Utgarde Keep | `wotlk-uk` | Full boss scripts |
| The Nexus | `wotlk-nex` | Full boss scripts |
| Azjol-Nerub | `wotlk-an` | Full boss scripts |
| Old Kingdom | `wotlk-ok` | Full boss scripts |
| Drak'Tharon Keep | `wotlk-dtk` | Full boss scripts |
| Violet Hold | `wotlk-vh` | Full boss scripts |
| Gundrak | `wotlk-gd` | Full boss scripts |
| Halls of Stone | `wotlk-hos` | Full boss scripts |
| Halls of Lightning | `wotlk-hol` | Full boss scripts |
| The Oculus | `wotlk-occ` | Full boss scripts |
| Utgarde Pinnacle | `wotlk-up` | Full boss scripts |
| Culling of Stratholme | `wotlk-cos` | Full boss scripts |
| Trial of Champion | `wotlk-toc` | Full boss scripts |
| Halls of Reflection | `wotlk-hor` | Full boss scripts |
| Pit of Saron | `wotlk-pos` | Full boss scripts |
| Forge of Souls | `wotlk-fos` | Full boss scripts |

### Success Criteria

- [ ] Bots activate correct dungeon strategy when entering an instance
- [ ] Tank bot leads the group and calls pulls in party chat
- [ ] Healer bot calls out when mana is low
- [ ] DPS bots follow target priority instructions
- [ ] Bots call out boss mechanics in party chat
- [ ] Bots react to wipes ("Let's try a different approach...")
- [ ] Dungeon knowledge is loaded from YAML, not hardcoded
- [ ] Works for at least 5 dungeons end-to-end

---

## 10. Milestone 6: Observability Dashboard

**Goal:** A web-based dashboard showing real-time agent reasoning, memory
contents, cost tracking, and admin controls.
**Duration estimate:** 5–7 days.
**C++ changes:** None.
**Depends on:** Milestone 1.

### Dashboard Components

#### 6.1 Live Agent Feed

Server-Sent Events (SSE) endpoint streaming agent traces in real-time:

```
GET /api/traces/stream?bot_guid=1234

data: {"bot_guid":1234,"event":"chat_received","model":"claude-haiku-4-5",
       "thinking":"Player asked for help with a quest. I should offer to join.",
       "tool_calls":["say","remember_this"],"latency_ms":1200}

data: {"bot_guid":1234,"event":"idle_tick","model":"claude-haiku-4-5",
       "thinking":"I'm near Goldshire. I should look for quests.",
       "tool_calls":["set_rpg_mode"],"latency_ms":900}
```

#### 6.2 Bot Roster

Real-time table of all elevated bots:

| Name | Personality | Zone | State | HP | Last Action | LLM Calls | Cost |
|------|------------|------|-------|-----|-------------|-----------|------|
| Thaldrin | gruff_warrior | Elwynn | idle | 100% | say "Aye." | 47 | $0.12 |
| Elariel | cheerful_healer | Stormwind | non-combat | 95% | emote wave | 23 | $0.08 |

#### 6.3 Memory Browser

Search and browse a bot's long-term memories:

```
GET /api/bots/1234/memories?query=player+interactions&limit=20
```

Displays: memory content, type, importance, creation date, related players.

#### 6.4 Cost Dashboard

```
Hourly Spend:    $1.23 / $5.00 limit
Total Spend:     $14.56
Active Agents:   12 / 50 max
Calls This Hour: 342
Avg Latency:     1.8s

Model Distribution:
  claude-haiku-4-5:   89% of calls
  claude-sonnet-4-5:  11% of calls
```

#### 6.5 Admin Controls

- Elevate / demote bots via UI buttons
- Hot-swap personality profiles
- Clear bot memories
- Adjust cost limits
- Force a bot to say something (debug tool)

### Technology

- **Backend:** FastAPI endpoints (already partially built in `api/`)
- **Frontend:** HTMX + minimal CSS. No JavaScript framework. Server-rendered
  HTML with HTMX for interactivity and SSE for live updates.
- **Metrics:** Prometheus counters exposed at `/metrics`, optionally scraped by Grafana

### Success Criteria

- [ ] Dashboard loads at `http://localhost:8080/`
- [ ] Live feed updates in real-time as bots interact
- [ ] Memory browser returns searchable results
- [ ] Cost tracking is accurate to within 1%
- [ ] Admin can elevate/demote bots from the UI
- [ ] Dashboard works on mobile (responsive)

---

## 11. Milestone 7: Scale to 50+ Active Agents

**Goal:** Support 50 simultaneously active LLM agents without degrading game
server performance or exceeding cost budgets.
**Duration estimate:** 5–7 days.
**C++ changes:** None.
**Depends on:** Milestones 1–6.

### Scaling Challenges

| Challenge | Solution |
|-----------|----------|
| 50 bots × 6 TCP queries per tick = 300 queries/tick | Connection pool (8 connections), parallel queries via asyncio.gather |
| 50 bots × 1 LLM call/tick = 16 calls/sec at 3s interval | Rate limiter: max 6 calls/bot/min, stagger ticks |
| API cost at 50 bots × 30 calls/hr = 1500 calls/hr | Model routing (Haiku default), global budget circuit breaker |
| Memory: 50 bots × 1000 memories each = 50K vectors | Qdrant handles millions — no issue |
| Context window: large state for 50 bots | Keep context under 2K tokens per call |

### 7.1 Tick Staggering

Instead of polling all 50 bots simultaneously, stagger across the tick interval:

```python
async def _tick(self):
    profiles = self._registry.all_elevated()
    batch_size = 10  # poll 10 bots per sub-tick
    for i in range(0, len(profiles), batch_size):
        batch = profiles[i:i+batch_size]
        await self._poll_and_dispatch(batch)
        await asyncio.sleep(self._tick_interval / (len(profiles) / batch_size))
```

### 7.2 Smart LLM Call Avoidance

Not every event needs an LLM call. Add increasingly aggressive filtering:

```python
# Priority 1: Always call LLM
CHAT_RECEIVED, GROUP_INVITE

# Priority 2: Call LLM once per encounter
COMBAT_START, BOT_DIED

# Priority 3: Call LLM occasionally (personality-dependent)
ZONE_CHANGED, IDLE_TICK

# Priority 4: Never call LLM
TARGET_CHANGED, ACTION_CHANGED, STRATEGY_CHANGED, STATE_SNAPSHOT
```

### 7.3 Response Caching

For identical situations, cache the LLM's tool-call pattern:

```python
cache_key = hash((personality_id, event_type, state_summary))
if cache_key in response_cache and cache_entry.age < 60:
    # Vary the cached response slightly (different emote, minor text change)
    return vary(cache_entry.response)
```

### 7.4 Automatic Elevation/Demotion

Instead of manual elevation only, add automatic triggers:

```python
class AutoElevator:
    def check(self, bot_guid: int, snapshot: BotSnapshot) -> bool:
        """Should this bot be elevated to LLM mode?"""
        # Elevate if a real player is within interaction range
        # Demote if no real players nearby for > 5 minutes
        # Respect max_active_agents limit
```

This means bots seamlessly transition between rule-engine and LLM mode
based on player proximity — the 200-500 bots feel alive when players are
near them, but don't burn API costs when no one is around.

### 7.5 Connection Pool Scaling

At 50 bots × 6 queries = 300 queries per tick:
- Each TCP query takes ~2ms on Docker network
- With 8 connections, throughput = 4000 queries/sec
- 300 queries = 75ms total — well within the 3-second tick budget

No changes needed — the existing pool handles this.

### Success Criteria

- [ ] 50 bots elevated simultaneously without errors
- [ ] Tick cycle completes within 3 seconds consistently
- [ ] API costs stay within configured hourly budget
- [ ] Game server CPU/memory impact < 5% increase
- [ ] Bots near players feel responsive; distant bots are silent
- [ ] Auto-elevation works based on player proximity
- [ ] Graceful degradation when API rate limits are hit

---

## Appendix A: Existing Bot Command Reference

### TCP Read Commands (PlayerbotCommandServer)

| Command | Response Format | Example |
|---------|----------------|---------|
| `state` | `combat\|dead\|non-combat` | `non-combat` |
| `position` | `X Y Z mapId orientation \|zoneName\|` | `1234.5 567.8 89.0 0 3.14 \|Elwynn Forest\|` |
| `tpos` | `X Y Z mapId orientation` (target) | `1230.0 570.0 89.0 0 1.57` |
| `movement` | `X Y Z mapId orientation` (last move) | Same format |
| `target` | Target name (empty if none) | `Murloc` |
| `hp` | `botHp% / targetHp%` | `85% / 60%` |
| `strategy` | Comma-separated strategy list | `combat ranged,heal,debuffs` |
| `action` | Last action name | `cast heal` |
| `values` | Formatted AI context values (debug) | Multi-line debug output |
| `travel` | Travel target info | `Destination = Stormwind` |

### Chat Commands (via `do` prefix through TCP or ExternalEventHelper)

**Chat:** `say <msg>`, `yell <msg>`, `whisper <name> <msg>`,
`#p <msg>` (party), `#r <msg>` (raid), `#g <msg>` (guild)

**Emote:** `emote <name>` (wave, bow, laugh, cry, dance, cheer, sit, kneel,
point, roar, salute, flex, shrug, clap, thank, beg)

**Strategy:** `co +<strategy>`, `co -<strategy>`, `co <full_strategy_set>`

**Combat:** `attack <target>`, `flee`, `stay`, `follow <player>`

**Quest:** `accept quest`, `drop`, `share`, `quests`, `q <quest_id>`

**Trade:** `t <player> <item> [count]`, `b <item>` (buy), `s <item>` (sell)

**Group:** `invite <player>`, `accept`, `leave`, `give leader <player>`

**Guild:** `ginvite <player>`, `guild promote <player>`, `guild demote <player>`

**Utility:** `repair`, `taxi`, `teleport`, `bank`, `home`, `help`

**Info:** `stats`, `reputation`, `spells`, `talents`, `items`, `inventory`

---

## Appendix B: Personality Profile Schema

```yaml
# Required fields
name: "Display Name"          # Used in logs and dashboard
class: "warrior"              # WoW class (warrior, mage, priest, etc.)
race: "dwarf"                 # WoW race
spec: "protection"            # Talent spec

# Character
backstory: >                  # 2-3 sentences, injected into system prompt
  A grizzled veteran who...
personality_traits:            # List of trait descriptions
  - "gruff but loyal"
  - "distrusts magic"
speech_patterns:               # How the character talks
  - "uses terse sentences"
  - "says 'ye' instead of 'you'"

# Behavior tuning
response_style:
  verbosity: "low"            # low | medium | high
  emote_frequency: 0.3        # 0.0-1.0, how often to add emotes
  initiation_threshold: 0.5   # 0.0-1.0, how likely to start conversations

# Combat
combat_preferences:
  default_strategy: "tank assist"
  flee_at_hp_pct: 10

# Cost controls (per-bot override)
cost_controls:
  model: "claude-haiku-4-5-20251001"    # Default model for this personality
  max_tokens_per_response: 150          # Max output tokens
  max_llm_calls_per_hour: 30           # Rate limit

# Dungeon behavior (M5)
dungeon_role: "tank"          # tank | healer | dps | leader
```

---

## Appendix C: Cost Projections

### Per-Call Cost (approximate)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Typical Call Cost |
|-------|----------------------|----------------------|-------------------|
| Claude Haiku 4.5 | $0.80 | $4.00 | ~$0.002 |
| Claude Sonnet 4.5 | $3.00 | $15.00 | ~$0.008 |

Assuming ~2000 input tokens (system prompt + context) and ~150 output tokens
per call.

### Monthly Cost Estimates

| Scenario | Active Bots | Calls/Bot/Hour | Model Mix | Monthly Cost |
|----------|------------|----------------|-----------|-------------|
| Light (dev/testing) | 5 | 20 | 100% Haiku | ~$15 |
| Medium (small server) | 20 | 25 | 90% Haiku, 10% Sonnet | ~$90 |
| Heavy (active server) | 50 | 30 | 85% Haiku, 15% Sonnet | ~$300 |

### Cost Controls Built In

1. **Per-bot rate limiter:** Token bucket, configurable calls/hour
2. **Model router:** Haiku for routine, Sonnet for important interactions
3. **Global hourly budget:** Circuit breaker at configurable USD/hour
4. **Auto-demotion:** Bots far from players revert to free rule-engine
5. **Response caching:** Deduplicates identical situations across bots

---

## Implementation Priority

```
M0 (Infrastructure)     ████████ [1-2 days]
M1 (Chat MVP)           ████████████████ [3-5 days]
M2 (Reactive Events)    ████████ [2-3 days]
M3 (Combat)             ██████████████████ [5-7 days]
M6 (Dashboard)          ██████████████████ [5-7 days]  ← can parallel with M3/M4
M4 (Questing/RPG)       ██████████████████████████ [7-10 days]
M5 (Dungeons/Raids)     ██████████████████████████████████ [10-14 days]
M7 (Scale)              ██████████████████ [5-7 days]
```

**Critical path:** M0 → M1 → M2 → M3 → M4 → M5
**Parallel track:** M6 can start after M1, independent of M3-M5
**Total estimated duration:** 6-10 weeks depending on testing depth
