# LLM Bot Middleware

The Python service that layers Claude on top of AzerothCore's
`mod-playerbots` to give bots personality, memory, and intelligent
behaviour. Runs alongside the worldserver as a separate container,
communicating over TCP (bot commands), SOAP (GM commands), and direct
MySQL reads (character/bot state).

For architecture, design decisions, and the full milestone roadmap see
[`DESIGN.md`](DESIGN.md). For acceptance scenarios per milestone see
[`USER_STORIES.md`](USER_STORIES.md). For the LLM-callable tool API see
[`TOOLS.md`](TOOLS.md).

## What it does

- **Talks**: bots respond in character to whispers, party/raid/guild chat
- **Remembers**: every conversation, grudge, and quest stored in Qdrant
- **Coordinates**: party loot rolls, quest sharing, dungeon roles, raid calls
- **Reacts**: combat events, low health, adds spawning, party member deaths
- **Scales**: 50+ active LLM agents simultaneously with cost control + rate limiting
- **Manages**: HTMX admin page for accounts, bots, builds, personalities,
  per-player toggles, kill switch

## Deployment on a new machine

### 1. Prerequisites

- Linux host (or Docker Desktop for Win/Mac)
- Docker + Docker Compose v2
- ~16 GB RAM if running 20+ active agents (~8 GB for a small dev setup)
- Outbound HTTPS to `api.anthropic.com`

### 2. Clone

```bash
git clone --recursive -b Playerbot \
    https://github.com/mattpadams/mod-playerbots.git azerothcore-wotlk
cd azerothcore-wotlk
```

`--recursive` is required to fetch `modules/mod-playerbots` at the right SHA.

### 3. Configure secrets

```bash
cp llm-bots/.env.example llm-bots/.env
```

Then edit `llm-bots/.env`:

```bash
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...                 # from console.anthropic.com
SOAP_USER=admin                              # matches the GM account you create later
SOAP_PASS=admin
DB_LLMBOTS=acore_llmbots                     # middleware-owned DB (auto-created)
```

Alternatively, leave `ANTHROPIC_API_KEY` blank and use Claude Code CLI
OAuth — run `claude login` on the host and the compose override mounts
`~/.claude/.credentials.json` into the container.

### 4. Configure AzerothCore

```bash
cp conf/dist/env.ac.dist conf/dist/env.ac
mkdir -p env/dist/etc env/dist/logs
cp env/dist/etc/worldserver.conf.dist env/dist/etc/worldserver.conf
cp env/dist/etc/authserver.conf.dist env/dist/etc/authserver.conf
cp env/dist/etc/modules/playerbots.conf.dist env/dist/etc/modules/playerbots.conf
```

Edit `env/dist/etc/worldserver.conf`:
```ini
SOAP.Enabled = 1
SOAP.IP = "0.0.0.0"
SOAP.Port = 7878
```

Edit `env/dist/etc/modules/playerbots.conf`:
```ini
AiPlayerbot.Enabled = 1
AiPlayerbot.commandServerPort = 8888
# Wake-on-event push from C++ to Python middleware (M2 hook):
AiPlayerbot.LlmBridgeEndpoint = "http://ac-bot-middleware:8180/events/chat"
```

### 5. First start

```bash
docker compose -f docker-compose.yml \
               -f llm-bots/docker-compose.override.yml \
               up -d --build
```

This first run takes 30-60 minutes because it:
1. Builds the worldserver from source (with `mod-playerbots` and the LLM bridge hook)
2. Imports the three game DBs (`acore_auth`, `acore_world`, `acore_characters`)
3. Downloads ~1 GB of pre-extracted client data via `ac-client-data-init`
4. Starts MySQL, Qdrant, worldserver, authserver, and the middleware

Watch the middleware boot:
```bash
docker logs -f ac-bot-middleware
```

Look for `app.starting` → `db.migrations.applied` → `qdrant.collection_ready`
→ `app.tool_server_ready` → `supervisor.started`. The middleware
auto-creates `acore_llmbots` and applies its schema on first start.

### 6. Create a GM account for SOAP

```bash
docker attach ac-worldserver
# Then in the worldserver console:
account create admin admin
account set gmlevel admin 3 -1
account set addon admin 2
# Detach with Ctrl+P Ctrl+Q
```

If you change the credentials, update `SOAP_USER`/`SOAP_PASS` in
`llm-bots/.env` and restart the middleware container.

### 7. Smoke test

| Endpoint | What you should see |
|---|---|
| <http://localhost:8080> | Empty roster, zero cost — the live dashboard |
| <http://localhost:8080/admin> | Admin page with kill switch, accounts/bots/builds CRUD |
| <http://localhost:8080/memories> | Empty memory grid (fills as bots converse) |
| <http://localhost:8180/health> | `{"status":"ok"}` |
| <http://localhost:8180/metrics> | Prometheus metrics (counters, histograms, gauges) |

Then in the admin page:
1. **Accounts** → create `bot01/secret` (creates a real WoW account via SOAP)
2. **Bots** → create a character on that account; pick class/race/level
3. **Assignments** → enter your player GUID, assign the bot to party slot 0
4. Log into the worldserver with your own character and the bot will
   auto-elevate when you're nearby (proximity scanner)

## Architecture in one paragraph

The middleware runs an `AgentSupervisor` that polls every active
elevated bot via TCP every 3 s, diffs snapshots into typed `GameEvent`s,
routes them through an `EventPolicy` registry to decide whether to call
the LLM, fetches enrichment context (party state, attacker count, party
loot/quest state, dungeon role) on demand, and dispatches the LLM
response as game commands or chat. A separate event bus accepts pushed
events from a C++ hook (`LlmBridgeHook`) so chat triggers don't have to
wait for the next poll. Memories go to Qdrant, traces to SQLite, costs
through a `CostController` with rate-limit degradation. The HTMX
dashboard reads `AgentSupervisor` state directly and the admin page
talks to a typed v2 API (`/api/v2/*`) backed by service classes over
SQLAlchemy repos.

## Operations

### Scaling

```bash
# llm-bots/.env
MAX_ACTIVE_AGENTS=50
AGENT_TICK_SECONDS=3
TICK_BATCH_SIZE=10              # max concurrent in-flight LLM calls
TICK_BATCH_SPACING_MS=500       # pacing between batches
MAX_HOURLY_SPEND_USD=5.00       # global cost breaker
```

### Cost control

The `CostController` tracks per-bot and global spend. When an hour
exceeds `MAX_HOURLY_SPEND_USD`, the global breaker opens and every
`select_model` returns `None` (no LLM calls) until the hour rolls over.
Per-bot rate limiting also degrades agents that hit the per-minute cap
— degraded bots stop being ticked for a configurable window.

### Kill switch

The admin page has a "Kill switch" toggle that flips
`settings.llm_kill_switch`. When on, every `BotAgent.handle_event` and
every `CostController.select_model` short-circuits, dropping the bot
back to the rule engine instantly. Re-enable to resume LLM calls.

### Per-player gating

Each player has a `player_settings` row with `bots_enabled` and
`llm_enabled` toggles. The `PartyLogoffChecker` enforces these every
30 s (logging off the actual game characters), and the bot agent's hot
path checks an in-memory `player_policy` cache (refreshed by the same
checker) so disabled players' bots never spend a token.

### Memory

`memory/qdrant_store.py` writes embeddings via sentence-transformers
to a `bot_memories` collection. Each bot's memory is queried by
similarity at LLM-call time and the top-K results are injected into
the prompt. To purge a bot's memory: `DELETE /api/admin/bots/{guid}/memories`.

### Traces

Every LLM call writes a row to `data/traces.db` (SQLite, mounted from
the host). The dashboard streams new traces over SSE. Useful for
debugging tool-call mistakes or runaway costs.

### Logs

Structlog → JSON-ish console output. Tail with:
```bash
docker logs -f ac-bot-middleware | jq -R 'fromjson? // .'
```

## Backups

The only persistent state owned by the middleware:

- **MySQL `acore_llmbots`** — admin tables (accounts, bots, builds, personalities, assignments, settings)
- **Qdrant volume `ac-qdrant-data`** — bot memories
- **SQLite `data/traces.db`** — observability trace log (rebuildable)
- **Personality YAMLs in `personality/`** — checked into git, not runtime state

Snapshot the first two daily.

## Updates

```bash
git pull
git submodule update --init --recursive
docker compose -f docker-compose.yml \
               -f llm-bots/docker-compose.override.yml \
               up -d --build ac-bot-middleware
```

DB migrations are idempotent; the middleware reapplies them on start.

## Troubleshooting

**Worldserver won't start, "loading maps" fails**
→ The `ac-client-data-init` step didn't complete. Check
`docker logs ac-client-data-init`; usually a network failure during
the ~1 GB download. Retry: `docker compose up ac-client-data-init`.

**Middleware logs show `db.engine_init_failed`**
→ MySQL isn't reachable. Check `DB_HOST` in `.env` (must be
`ac-database` for the docker-network case).

**Every LLM call returns 422**
→ The `htmx-ext-json-enc` extension isn't loading in the dashboard.
Hard-refresh the page; the script is loaded from unpkg in `base.html`.

**Bot agents never elevate when a player logs in**
→ `ProximityScanner` requires `aiomysql` and read access to
`acore_playerbots`. Confirm `DB_PLAYERBOTS=acore_playerbots` and that
the worldserver has populated the `playerbots_random_bots` table.

**SOAP `account create` returns empty**
→ `SOAP.Enabled = 1` is missing in `worldserver.conf`, or the
`SOAP_USER`/`SOAP_PASS` in `.env` don't match a real GM account.
The middleware now rolls back on this, so you won't get orphan
WoW accounts, but you'll see `account_service.create_failed` in the
logs.

**Inner mod-playerbots build fails**
→ `git submodule update --init --recursive` from the repo root.
The submodule pin is on `mattpadams/mod-playerbots` branch
`llm-integration` — see commit `0af0f4a4` for the LLM-integration C++.

## Related docs

- [`DESIGN.md`](DESIGN.md) — full architecture, milestone-by-milestone design notes
- [`USER_STORIES.md`](USER_STORIES.md) — acceptance scenarios for each feature
- [`TOOLS.md`](TOOLS.md) — every LLM-callable bot tool, parameters, and game command mapping
- [`docker-compose.override.yml`](docker-compose.override.yml) — middleware container wiring
- [`.env.example`](.env.example) — all configurable settings with sensible defaults

## Licence

GPL v2 (inherits from AzerothCore). See repo-root `LICENSE`.
