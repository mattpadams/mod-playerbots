# LLM Bot Tools Reference

All tools are registered on a single persistent MCP server (`azeroth-bots`)
created at startup. Every tool takes `bot_guid` as a required input parameter
so the same server instance serves all bots.

**MCP tool name format:** `mcp__azeroth-bots__{tool_name}`

---

## Chat Tools

Source: `bot_agents/tools/chat_tools.py`

### say

Speak aloud so nearby players and NPCs can hear you.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `message` | string | yes | What to say |

**Game command:** `do say {message},{bot_guid}`

---

### yell

Yell loudly so players in a wide area can hear you.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `message` | string | yes | What to yell |

**Game command:** `do yell {message},{bot_guid}`

---

### whisper

Send a private message to a specific player.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `target_player` | string | yes | Player name to whisper |
| `message` | string | yes | What to whisper |

**Game command:** `do whisper {target_player} {message},{bot_guid}`

---

### party_chat

Send a message to your party or group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `message` | string | yes | What to say in party |

**Game command:** `do #p {message},{bot_guid}`

---

### guild_chat

Send a message to your guild.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `message` | string | yes | What to say in guild |

**Game command:** `do #g {message},{bot_guid}`

---

### emote

Perform an in-game emote to express yourself physically.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `emote_name` | string | yes | Emote to perform |

**Available emotes:** wave, bow, laugh, cry, dance, cheer, sit, kneel, point, roar, salute, flex, shrug, clap, thank, beg

**Game command:** `do emote {emote_name},{bot_guid}`

---

## Combat & Strategy Tools

Source: `bot_agents/tools/combat_tools.py`

### change_strategy

Change your combat or behavior strategy. The rule engine handles real-time
spell rotation — this tool controls the *strategic* layer.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `strategy` | string | yes | Strategy change expression |

**Strategy syntax:**
- `+strategy_name` — add a strategy
- `-strategy_name` — remove a strategy
- Comma-separated for multiple: `+tank assist,+aoe,-ranged`

**Available strategies:**

| Category | Strategies |
|----------|-----------|
| Role | `tank assist`, `dps assist`, `heal` |
| Range | `ranged`, `close` (melee) |
| Behavior | `aggressive`, `passive`, `flee` |
| Combat | `aoe`, `cc` (crowd control), `pull` |
| RPG | `rpg`, `grind`, `travel`, `loot` |
| Social | `follow`, `stay`, `emote`, `guild` |

**Game command:** `do co {strategy},{bot_guid}`

---

### follow_player

Follow a specific player, staying close to them as they move.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `player_name` | string | yes | Player to follow |

**Game command:** `do follow {player_name},{bot_guid}`

---

### stay

Stop moving and hold your current position.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |

**Game command:** `do stay,{bot_guid}`

---

### flee

Run away from combat. Use when health is critical or the fight is unwinnable.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |

**Game command:** `do flee,{bot_guid}`

---

### invite_to_group

Invite a player to join your group or party.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `player_name` | string | yes | Player to invite |

**Game command:** `do invite {player_name},{bot_guid}`

---

### accept_group_invite

Accept a pending group invitation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |

**Game command:** `do accept,{bot_guid}`

---

### leave_group

Leave your current party or raid group.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |

**Game command:** `do leave,{bot_guid}`

---

## Memory Tools

Source: `bot_agents/tools/memory_tools.py`

### remember_this

Store something important to your long-term memory. Persisted in Qdrant
vector database. Use for facts about players, events, promises, or
lessons learned.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `content` | string | yes | What to remember |
| `memory_type` | string | no | Category (default: `conversation`) |

**Memory types:** `conversation`, `relationship`, `world_event`, `personality`

**Backend:** Embedded with `all-MiniLM-L6-v2` (384-dim), stored in Qdrant.

---

### recall

Search your long-term memory for information about a topic, player, or event.
Returns the top 5 most semantically relevant memories.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `bot_guid` | integer | yes | Your bot GUID |
| `query` | string | yes | What to search for |

**Backend:** Cosine similarity search in Qdrant, filtered by `bot_guid`.
Uses multi-query Reciprocal Rank Fusion (situational + player + personality).

---

## Planned Tools (Future Milestones)

### Milestone 3: Combat

| Tool | Description | Parameters |
|------|-------------|------------|
| `set_focus_target` | Tell the group to focus a specific enemy | `bot_guid`, `target_name` |
| `use_ability` | Use a specific combat ability | `bot_guid`, `ability_name`, `target_name` |
| `request_heal` | Ask the healer for healing | `bot_guid` |

### Milestone 4: Questing & Trading

| Tool | Description | Parameters |
|------|-------------|------------|
| `accept_quest` | Accept a quest from a nearby NPC | `bot_guid`, `quest_name_or_id` |
| `drop_quest` | Abandon a quest | `bot_guid`, `quest_name_or_id` |
| `list_quests` | List quests in your quest log | `bot_guid` |
| `share_quest` | Share a quest with party members | `bot_guid`, `quest_name_or_id` |
| `trade_item` | Initiate a trade with a player | `bot_guid`, `player_name`, `item_name`, `quantity` |
| `buy_from_vendor` | Buy from a nearby vendor | `bot_guid`, `item_name`, `quantity` |
| `sell_to_vendor` | Sell to a nearby vendor | `bot_guid`, `item_name` |
| `set_rpg_mode` | Change RPG behavior (grind, travel, quest, rest, idle, explore) | `bot_guid`, `mode` |
| `go_to_location` | Travel to a named location or coordinates | `bot_guid`, `destination` |

### Milestone 5: Dungeon & Raid

| Tool | Description | Parameters |
|------|-------------|------------|
| `set_dungeon_strategy` | Activate dungeon-specific strategy | `bot_guid`, `dungeon_key` |
| `call_out_mechanic` | Warn party about a boss mechanic | `bot_guid`, `message` |
| `mark_target` | Set a raid target icon on an enemy | `bot_guid`, `target_name`, `icon` |
| `ready_check` | Ask the group if they are ready | `bot_guid` |

---

## Tool Registration Architecture

```
Startup:
  ToolServer(executor, memory_manager)
    -> create_chat_tools(executor)        # 6 tools
    -> create_combat_tools(executor)      # 7 tools
    -> create_memory_tools(memory_manager) # 2 tools
    = 15 tools total

  ClaudeProvider.init_mcp_server(tools, tool_names)
    -> _wrap_tools_for_sdk(tools)         # re-applies claude_agent_sdk.tool
    -> create_sdk_mcp_server("azeroth-bots", tools)
    = 1 persistent MCP server

Per query:
  ClaudeSDKClient(
    mcp_servers={"azeroth-bots": <same server>},
    system_prompt="...Your bot GUID is 1234. Pass bot_guid=1234 to every tool call.",
    model="claude-haiku-4-5",
  )
```

All tools close over shared services (`CommandExecutor`, `MemoryManager`).
Bot identity is passed as `bot_guid` input parameter by the LLM at call time.
