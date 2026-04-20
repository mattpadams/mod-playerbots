-- Initial schema for acore_llmbots.
-- Statements are separated by a single ";" followed by newline.

CREATE TABLE llm_settings (
    key_name    VARCHAR(64)  NOT NULL PRIMARY KEY,
    value_json  TEXT         NOT NULL,
    updated_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE personality_templates (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(64)  NOT NULL UNIQUE,
    yaml_data   MEDIUMTEXT   NOT NULL,
    created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3),
    INDEX idx_personality_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE build_templates (
    id            INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(64)  NOT NULL UNIQUE,
    class_id      TINYINT UNSIGNED NOT NULL,
    race_id       TINYINT UNSIGNED NOT NULL,
    spec_index    TINYINT UNSIGNED NOT NULL DEFAULT 0,
    level         TINYINT UNSIGNED NOT NULL DEFAULT 1,
    gear_tier     VARCHAR(32)  NOT NULL DEFAULT 'starter',
    starting_zone VARCHAR(64)  NOT NULL DEFAULT '',
    personality   VARCHAR(64)  NOT NULL DEFAULT 'default',
    notes         TEXT,
    created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE managed_accounts (
    id                INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username          VARCHAR(32)  NOT NULL UNIQUE,
    owner_player_guid INT UNSIGNED,
    notes             TEXT,
    created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_accounts_owner (owner_player_guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE managed_bots (
    id                INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id        INT UNSIGNED NOT NULL,
    character_guid    INT UNSIGNED NOT NULL UNIQUE,
    character_name    VARCHAR(12)  NOT NULL,
    class_id          TINYINT UNSIGNED NOT NULL,
    race_id           TINYINT UNSIGNED NOT NULL,
    level             TINYINT UNSIGNED NOT NULL DEFAULT 1,
    build_template_id INT UNSIGNED,
    personality_name  VARCHAR(64)  NOT NULL DEFAULT 'default',
    created_at        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_managed_bots_account
        FOREIGN KEY (account_id) REFERENCES managed_accounts(id) ON DELETE CASCADE,
    CONSTRAINT fk_managed_bots_build
        FOREIGN KEY (build_template_id) REFERENCES build_templates(id) ON DELETE SET NULL,
    INDEX idx_managed_bots_account (account_id),
    INDEX idx_managed_bots_guid (character_guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE player_bot_assignments (
    id            INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    player_guid   INT UNSIGNED NOT NULL,
    bot_guid      INT UNSIGNED NOT NULL,
    party_slot    TINYINT UNSIGNED NOT NULL,
    slot_position TINYINT UNSIGNED NOT NULL,
    assigned_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_player_bot (player_guid, bot_guid),
    INDEX idx_assignments_player (player_guid),
    INDEX idx_assignments_bot (bot_guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE player_settings (
    player_guid  INT UNSIGNED NOT NULL PRIMARY KEY,
    bots_enabled TINYINT(1)   NOT NULL DEFAULT 1,
    llm_enabled  TINYINT(1)   NOT NULL DEFAULT 1,
    updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
        ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO llm_settings (key_name, value_json) VALUES
    ('llm_kill_switch', 'false'),
    ('llm_model_override', '""');
