from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM provider
    llm_provider: str = "claude"
    llm_model: str = ""  # empty = use provider default
    anthropic_api_key: str = ""  # set via ANTHROPIC_API_KEY; fallback to OAuth if empty

    # Game server
    ws_host: str = "ac-worldserver"
    ws_cmd_port: int = 8888
    ws_soap_port: int = 7878
    soap_user: str = "admin"
    soap_pass: str = "admin"

    # Database
    db_host: str = "ac-database"
    db_port: int = 3306
    db_user: str = "root"
    db_pass: str = "password"
    db_playerbots: str = "acore_playerbots"
    db_characters: str = "acore_characters"
    db_auth: str = "acore_auth"
    # Middleware-owned persistence (admin UI state, templates, assignments)
    db_llmbots: str = "acore_llmbots"

    # Qdrant
    qdrant_host: str = "ac-qdrant"
    qdrant_port: int = 6333

    # Agent tuning
    max_active_agents: int = 50
    agent_tick_seconds: float = 3.0
    max_hourly_spend_usd: float = 5.0

    # Milestone 7: scale tuning
    # Tick staggering — split the per-tick poll + LLM fan-out into chunks
    # so 50 bots do not all hit the game server / Anthropic at the same
    # millisecond. tick_batch_size of 10 at 50ms spacing keeps a 50-bot
    # fleet under a 250ms burst window.
    tick_batch_size: int = 10
    tick_batch_spacing_ms: int = 50

    # Milestone 7: proximity-based auto-elevation
    # Radius (yards) inside which a bot is considered "near a player" for
    # auto-elevation purposes. Game's own "nearby" range is ~100y.
    proximity_radius_yards: float = 100.0
    # How often the proximity scanner queries the characters DB.
    proximity_scan_interval_seconds: float = 5.0
    # Toggle auto-elevation off to fall back to manual-only elevation.
    auto_elevation_enabled: bool = True
    # Auto-elevated bots are demoted after this many consecutive ticks
    # with no human nearby. Admin-elevated (pinned) bots never auto-demote.
    auto_demote_grace_ticks: int = 3
    # Default personality used when the auto-elevator promotes a new bot.
    auto_elevation_personality: str = "default"

    # Milestone 7: budget + rate-limit degradation
    # Once hourly spend crosses this fraction of the cap, the cost
    # controller downgrades "important" events to the default model to
    # stretch the remaining budget. At 1.0 we stop calling the API.
    budget_degrade_threshold: float = 0.8
    # How long the global rate-limit circuit stays open after repeated
    # 429s from the provider.
    rate_limit_global_backoff_seconds: float = 30.0
    # How long an individual bot is marked degraded after a provider 429.
    rate_limit_per_bot_backoff_seconds: float = 60.0
    # Consecutive 429s (across all bots) that trigger the global breaker.
    rate_limit_global_trigger: int = 3

    # Proactive (idle-tick) behavior — off by default to protect budget;
    # individual personality profiles opt in with ``proactive_enabled: true``.
    proactive_enabled: bool = False
    # Emit an IdleTickEvent after this many consecutive empty ticks.
    proactive_idle_ticks: int = 10

    # Model routing (used by cost_controller for event-based model selection)
    model_default: str = "claude-haiku-4-5"
    model_important: str = "claude-sonnet-4-6"

    # Admin-mutable runtime controls (loaded from llm_settings on startup,
    # persisted on change). Empty override keeps tier-based routing.
    llm_kill_switch: bool = False
    llm_model_override: str = ""

    # Observability dashboard (Milestone 6)
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    trace_db_path: str = "data/traces.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
