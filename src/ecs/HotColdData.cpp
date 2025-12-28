/*
 * ECS Hot/Cold Data Sync Implementation
 */

#include "HotColdData.h"
#include "Player.h"
#include "Spell.h"
#include "Group.h"

namespace ecs {

void HotDataSync::SyncFromPlayer(::Player* player, HotData& hot)
{
    if (!player)
        return;

    // Position
    hot.x = player->GetPositionX();
    hot.y = player->GetPositionY();
    hot.z = player->GetPositionZ();
    hot.orientation = player->GetOrientation();
    hot.mapId = player->GetMapId();

    // Spatial cells (32-yard cells)
    constexpr float CELL_SIZE = 32.0f;
    hot.cellX = static_cast<int16_t>(hot.x / CELL_SIZE);
    hot.cellY = static_cast<int16_t>(hot.y / CELL_SIZE);
    hot.zoneId = static_cast<uint16_t>(player->GetZoneId());
    hot.areaId = static_cast<uint16_t>(player->GetAreaId());

    // Vitals
    hot.health = player->GetHealth();
    hot.power = player->GetPower(player->getPowerType());

    uint32_t maxHealth = player->GetMaxHealth();
    uint32_t maxPower = player->GetMaxPower(player->getPowerType());

    hot.healthPct = maxHealth > 0 ? static_cast<uint16_t>((hot.health * 10000) / maxHealth) : 10000;
    hot.powerPct = maxPower > 0 ? static_cast<uint16_t>((hot.power * 10000) / maxPower) : 10000;

    // Quick stats
    hot.level = static_cast<uint16_t>(player->GetLevel());
    hot.classId = player->getClass();
    hot.raceId = player->getRace();

    // Combat flags
    hot.combatFlags = PackCombatFlags(player);

    // Target
    if (Unit* target = player->GetVictim())
    {
        hot.targetGuidLow = target->GetGUID().GetCounter();
    }
    else
    {
        hot.targetGuidLow = 0;
    }
}

void HotDataSync::SyncColdFromPlayer(::Player* player, ColdData& cold)
{
    if (!player)
        return;

    cold.playerGuid = player->GetGUID().GetRawValue();
    cold.accountId = player->GetSession() ? player->GetSession()->GetAccountId() : 0;

    // Stats
    cold.maxHealth = player->GetMaxHealth();
    cold.maxPower = player->GetMaxPower(player->getPowerType());
    cold.attackPower = player->GetTotalAttackPowerValue(BASE_ATTACK);
    cold.spellPower = player->GetBaseSpellPowerBonus();
    cold.armor = player->GetArmor();
    cold.critChance = player->GetFloatValue(PLAYER_CRIT_PERCENTAGE);

    // Group info
    if (Group* group = player->GetGroup())
    {
        cold.groupGuid = group->GetGUID().GetRawValue();
        cold.raidSubgroup = group->GetMemberGroup(player->GetGUID());
    }
    else
    {
        cold.groupGuid = 0;
        cold.raidSubgroup = 0;
    }
}

uint8_t HotDataSync::PackCombatFlags(::Player* player)
{
    uint8_t flags = 0;

    if (player->IsInCombat())
        flags |= 0x01;

    if (player->IsNonMeleeSpellCast(false))
        flags |= 0x02;

    if (player->isMoving())
        flags |= 0x04;

    if (player->GetCurrentSpell(CURRENT_CHANNELED_SPELL))
        flags |= 0x08;

    if (player->isDead())
        flags |= 0x10;

    if (player->HasUnitState(UNIT_STATE_STUNNED))
        flags |= 0x20;

    if (player->HasUnitState(UNIT_STATE_FLEEING))
        flags |= 0x40;

    if (player->HasUnitState(UNIT_STATE_ROOT))
        flags |= 0x80;

    return flags;
}

} // namespace ecs
