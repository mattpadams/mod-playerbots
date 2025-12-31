/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#ifndef _PLAYERBOT_LOOTQUESTCONTAINERACTION_H
#define _PLAYERBOT_LOOTQUESTCONTAINERACTION_H

#include "ContainerQuestObjectiveValue.h"
#include "MovementActions.h"

class PlayerbotAI;

// States for the container looting state machine
enum class ContainerLootState
{
    IDLE,
    SEEKING_CONTAINER,
    ENEMIES_DETECTED,
    WAITING_FOR_COMBAT,
    ASSISTING_COMBAT,
    LOOTING
};

class LootQuestContainerAction : public MovementAction
{
public:
    LootQuestContainerAction(PlayerbotAI* botAI)
        : MovementAction(botAI, "loot quest container"),
          state(ContainerLootState::IDLE),
          notifiedAboutEnemies(false),
          lastNotifyTime(0) {}

    bool Execute(Event event) override;
    bool isUseful() override;

private:
    // State handlers
    bool HandleSeekingContainer(ContainerQuestObjective& objective);
    bool HandleEnemiesDetected(ContainerQuestObjective& objective);
    bool HandleWaitingForCombat(ContainerQuestObjective& objective);
    bool HandleAssistingCombat();
    bool HandleLooting(ContainerQuestObjective& objective);

    // Helper methods
    bool CheckForEnemiesNearContainer(ContainerQuestObjective& objective, GuidVector& outEnemies);
    void NotifyPlayerAboutEnemies(ContainerQuestObjective& objective, size_t enemyCount);
    bool IsMasterInCombat();
    void SetLootTarget(ContainerQuestObjective& objective);

    ContainerLootState state;
    bool notifiedAboutEnemies;
    time_t lastNotifyTime;
    ObjectGuid currentTargetContainer;

    static constexpr float CONTAINER_DETECTION_RANGE = 30.0f;
    static constexpr float ENEMY_SAFETY_RADIUS = 10.0f;  // Reduced from 40 - only avoid very close enemies
    static constexpr int NOTIFY_COOLDOWN_SECONDS = 30;
};

#endif
