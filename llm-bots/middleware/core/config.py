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

    # Qdrant
    qdrant_host: str = "ac-qdrant"
    qdrant_port: int = 6333

    # Agent tuning
    max_active_agents: int = 50
    agent_tick_seconds: float = 3.0
    max_hourly_spend_usd: float = 5.0

    # Model routing (used by cost_controller for event-based model selection)
    model_default: str = "claude-haiku-4-5"
    model_important: str = "claude-sonnet-4-6"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
