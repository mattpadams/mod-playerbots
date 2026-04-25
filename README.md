# AzerothCore + LLM Playerbots

A fork of [AzerothCore](https://www.azerothcore.org) (WoW 3.3.5a server emulator)
plus an LLM middleware layer that gives [`mod-playerbots`](https://github.com/mod-playerbots/mod-playerbots)
characters real personality, persistent memory, and intelligent
behaviour, powered by Anthropic's Claude.

The classic playerbot rule engine still drives second-by-second combat
execution. The LLM acts as a strategic brain: it talks, decides what
the bot is doing this minute, remembers players and grudges, and
coordinates parties and raids in character.

## What's in this repo

| Path | Contents |
|---|---|
| `src/`, `apps/`, `deps/`, `data/` | Stock AzerothCore (C++ + SQL) |
| `modules/mod-playerbots/` | mod-playerbots C++ module (submodule, pinned to fork) |
| `llm-bots/` | LLM middleware — Python FastAPI service, Docker compose, docs |
| `llm-bots/middleware/` | The middleware itself (FastAPI + SQLAlchemy + HTMX dashboard) |
| `llm-bots/DESIGN.md` | Full architecture, milestone roadmap, design decisions |
| `llm-bots/USER_STORIES.md` | Per-milestone acceptance scenarios |
| `llm-bots/TOOLS.md` | Reference for every LLM-callable bot tool |
| `llm-bots/README.md` | Deployment guide and middleware operations |

## Quick start (fresh machine)

```bash
git clone --recursive -b Playerbot \
    https://github.com/mattpadams/mod-playerbots.git azerothcore-wotlk
cd azerothcore-wotlk
cp llm-bots/.env.example llm-bots/.env       # add ANTHROPIC_API_KEY
cp conf/dist/env.ac.dist conf/dist/env.ac
docker compose -f docker-compose.yml \
               -f llm-bots/docker-compose.override.yml \
               up -d --build
```

The first build takes 30-60 minutes (worldserver compile) and downloads
~1 GB of pre-extracted client data automatically via the
`ac-client-data-init` service. See [`llm-bots/README.md`](llm-bots/README.md)
for the full bring-up checklist (worldserver.conf changes, SOAP account
setup, dashboard URLs, etc.).

## Status

All eight milestones plus the admin management surface are implemented
and pushed; pending in-game verification on a live worldserver. See the
status table in [`llm-bots/DESIGN.md`](llm-bots/DESIGN.md) for the
per-milestone breakdown.

## Upstream

- AzerothCore: <https://github.com/azerothcore/azerothcore-wotlk>
- mod-playerbots: <https://github.com/mod-playerbots/mod-playerbots>

This fork tracks both upstreams. Run `git fetch upstream` (outer) and
`git -C modules/mod-playerbots fetch origin` (inner) to pull updates.

## Licence

GPL v2 (inherited from AzerothCore). See [`LICENSE`](LICENSE).
