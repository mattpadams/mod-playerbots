# AzerothCore LLM Bots — User Stories

User stories describing what LLM-powered bots can do for players, guild
leaders, raiders, roleplayers, and server admins. Organized by milestone
so each story doubles as an acceptance target.

Legend: ✅ shipped · 🟡 in progress · ⏳ planned

---

## Milestone 1: Chat MVP ✅

**Story 1.1 — Talking to a bot in whisper**
As a solo player, I want to whisper a bot and get an in-character reply,
so the server feels populated even when no real players are online.

> `/w Thrargor hey what's up?`
> *Thrargor whispers*: "Been sharpening my axe, lad. These Scourge won't
> kill themselves. You need something?"

**Story 1.2 — Bots that remember me**
As a returning player, I want a bot I've spoken with before to remember
our last conversation, so interactions feel persistent rather than
amnesiac.

> Two weeks later:
> `/w Mirelle how's your sister?`
> *Mirelle whispers*: "Still in Stormwind recovering, thanks for asking.
> You said you'd bring her some Mageroyal — did you get it?"

**Story 1.3 — Distinct personalities**
As a roleplayer, I want different bots to have distinct voices and
backstories, so I can tell a cheerful healer apart from a cynical rogue
without checking their class.

**Story 1.4 — Natural emotes**
As a player, I want bots to use emotes (`/laugh`, `/nod`, `/sigh`) in
conversation, so their replies feel embodied rather than chat-window-only.

**Story 1.5 — Elevate/demote**
As a server admin, I want to elevate specific bots to LLM mode and demote
them back to the rule engine at will, so I can manage API costs by only
activating a small set of bots.

---

## Milestone 2: Reactive Events ✅

**Story 2.1 — Snappy whisper response**
As a player whispering a bot, I want a reply within ~3 seconds instead of
up to 6, so conversation feels natural rather than walkie-talkie-like.

**Story 2.2 — Party chat awareness**
As a group member, I want bots in my party to notice when I say something
in party chat and respond appropriately, so they feel like teammates, not
mute NPCs.

> `/p Anyone need a repair break?`
> *Mirelle (party)*: "I'm fine, but Thrargor's mail is practically falling
> off him."

**Story 2.3 — Guild chat presence**
As a guild officer, I want LLM-enabled guild bots to chime in on guild
chat occasionally with in-character commentary, so the guild feels alive
during off-hours.

---

## Milestone 3: Combat Integration ✅

**Story 3.1 — Strategic role choice**
As a tank in a 5-man, I want my bot healer to recognize when the group
enters combat and switch to a heal-focused strategy automatically, so I
don't have to micromanage `co +heal`.

**Story 3.2 — Situational callouts**
As a DPS bot in combat, I want to call out in party chat when something
important happens, so the group reacts like a real team.

> *Thrargor (party)*: "Got the caster, interrupting now."
> *Mirelle (party)*: "Mana low, drink break incoming."

**Story 3.3 — Self-preservation**
As a bot at 15% HP with no healer nearby, I want to flee and call for
help instead of dying, so I feel like an intelligent agent rather than a
suicidal NPC.

**Story 3.4 — Rule engine stays fast**
As a server operator, I don't want the LLM called on every combat tick —
only at key transitions (combat start, critical health, role change), so
spell rotations stay crisp and API costs stay sane.

> **Deferred from M3** (tracked in DESIGN.md): mana-low auto-callouts
> (→ M4), party-member-died reactions (→ M5), add-spawn AoE pivots (→ M5),
> boss phase detection (→ M5). The LLM can still call these out manually
> if it observes them — the deferred work is automated detection.

---

## Milestone 4: Questing, Trading, Full RPG ⏳

**Story 4.1 — Quest buddy**
As a questing player, I want to ask a nearby bot "want to do Hogger with
me?" and have them accept the quest, follow me, and help complete it, so
I don't need a real group for group quests.

**Story 4.2 — Quest sharing**
As a party leader, I want bots to share quests with me (or accept my
shared quests) based on what makes sense for their level and personality,
so we stay on the same objectives.

**Story 4.3 — Trading in character**
As a player short on bandages, I want to ask a bot for some and have
them actually trade based on personality — a cheerful healer might give
freely, a cynical rogue might haggle.

> `/w Zerik got any bandages to spare?`
> *Zerik whispers*: "Tch. Five silver a stack. Running a business here."

**Story 4.4 — Bots with their own goals**
As an observer, I want idle bots to decide what to do next based on
their personality and level — grinding, questing, exploring a zone, or
heading to town — so the world feels like it has its own life.

**Story 4.5 — Persistent quest progress**
As a player, I want a bot that started a quest chain with me yesterday
to remember where we left off and pick it up again today.

---

## Milestone 5: Dungeon & Raid Coordination ⏳

**Story 5.1 — Role-aware dungeon entry**
As a player zoning into a 5-man, I want the bots in my group to activate
the correct dungeon strategy automatically (tank pulls, healer ranges
correctly, DPS follows focus target), so I don't have to coach each one.

**Story 5.2 — Boss mechanic callouts**
As a player fighting a boss, I want bots to call out important mechanics
in party chat (kick this, move out of that, save cooldowns for phase 2),
so new players can learn fights from bot teammates.

> *Thrargor (party, tank)*: "Bone Storm incoming — spread!"

**Story 5.3 — Recovering from wipes**
As a party leader after a wipe, I want bots to regroup, acknowledge what
went wrong in character, and suggest a different approach, rather than
just resetting silently.

> *Mirelle (party)*: "My fault — let him grab me in the flame. Let's try
> again, keep Thrargor topped off first."

**Story 5.4 — Configurable dungeon knowledge**
As a server admin or module author, I want to add dungeon strategies
(pulls, mechanics, role priorities) via YAML files, so I don't have to
recompile the server to support new content.

---

## Milestone 6: Observability Dashboard ⏳

**Story 6.1 — Watch bots think in real time**
As a server admin, I want a live web dashboard showing which bots are
elevated, what events they're reacting to, and what the LLM decided, so
I can debug bad behavior without tailing logs.

**Story 6.2 — Search bot memories**
As a developer, I want to browse and search a bot's long-term memory
(Qdrant vectors), so I can verify memory recall is working and prune bad
entries.

**Story 6.3 — Cost visibility**
As a server operator paying for Claude API usage, I want a hard number
for "tokens/dollars spent per hour" on the dashboard, so I can set a
budget and catch runaway agents.

**Story 6.4 — One-click elevate/demote**
As a GM, I want to elevate or demote a bot from the dashboard with a
click, so I don't need to run a console command every time.

---

## Milestone 7: Scale to 50+ Active Agents ⏳

**Story 7.1 — Proximity-based activation**
As a player exploring a zone, I want bots near me to become LLM-enabled
automatically and bots far from any player to fall back to the rule
engine, so the world feels alive where I am without burning tokens
elsewhere.

**Story 7.2 — Hard budget cap**
As a server admin, I want to configure an hourly spending cap. When hit,
the system should gracefully degrade (fewer elevated bots, shorter
responses) instead of crashing or silently overspending.

**Story 7.3 — Server stays healthy under load**
As a player, I don't want the game server to stutter or lag because 50
bots are each making API calls. LLM traffic should never block the
world thread.

**Story 7.4 — Graceful rate limit handling**
As a server operator, when Anthropic rate-limits us during a raid, I
want affected bots to quietly fall back to rule-engine behavior and
resume LLM mode when headroom returns — no error spam in chat, no
frozen bots.

---

## Cross-cutting Stories

**Story X.1 — Never break the core server**
As a server admin, I want to be able to set `AiPlayerbot.LlmBridgeEndpoint = ""`
and have the entire LLM layer turn off cleanly, so I can disable it
instantly if something goes wrong. Nothing in `llm-bots/` should ever be
load-bearing for the core game.

**Story X.2 — Private API keys stay private**
As a server operator, I want my Anthropic credentials mounted read-only
from the host and never logged or exposed via any HTTP endpoint.

**Story X.3 — Plays nicely with existing mod-playerbots**
As a mod-playerbots contributor, I want the LLM layer to coexist with
the existing rule-engine AI — same bots, same commands, just smarter
decisions layered on top — so upstream changes don't break us.
