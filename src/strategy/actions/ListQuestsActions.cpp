/*
 * Copyright (C) 2016+ AzerothCore <www.azerothcore.org>, released under GNU AGPL v3 license, you may redistribute it
 * and/or modify it under version 3 of the License, or (at your option), any later version.
 */

#include "ListQuestsActions.h"

#include "Event.h"
#include "Playerbots.h"
#include "ChatHelper.h"

bool ListQuestsAction::Execute(Event event)
{
    std::string param = event.getParam();
    std::string source = event.GetSource();

    // Handle "progress" keyword said alone (via trigger) or as "quests progress"
    if (param == "progress" || param == "objectives" || param == "obj" ||
        source == "progress" || source == "objectives")
    {
        ListQuestsWithProgress();
    }
    else if (param == "completed" || param == "co")
    {
        ListQuests(QUEST_LIST_FILTER_COMPLETED);
    }
    else if (param == "incompleted" || param == "in")
    {
        ListQuests(QUEST_LIST_FILTER_INCOMPLETED);
    }
    else if (param == "all")
    {
        ListQuests(QUEST_LIST_FILTER_ALL);
    }
    else if (param == "travel")
    {
        ListQuests(QUEST_LIST_FILTER_ALL, QUEST_TRAVEL_DETAIL_SUMMARY);
    }
    else if (param == "travel detail")
    {
        ListQuests(QUEST_LIST_FILTER_ALL, QUEST_TRAVEL_DETAIL_FULL);
    }
    else
    {
        ListQuests(QUEST_LIST_FILTER_SUMMARY);
    }

    return true;
}

void ListQuestsAction::ListQuests(QuestListFilter filter, QuestTravelDetail travelDetail)
{
    bool showIncompleted = filter & QUEST_LIST_FILTER_INCOMPLETED;
    bool showCompleted = filter & QUEST_LIST_FILTER_COMPLETED;

    if (showIncompleted)
        botAI->TellMaster("--- Incompleted quests ---");

    uint32 incompleteCount = ListQuests(false, !showIncompleted, travelDetail);

    if (showCompleted)
        botAI->TellMaster("--- Completed quests ---");

    uint32 completeCount = ListQuests(true, !showCompleted, travelDetail);

    botAI->TellMaster("--- Summary ---");

    std::ostringstream out;
    out << "Total: " << (completeCount + incompleteCount) << " / 25 (incompleted: " << incompleteCount
        << ", completed: " << completeCount << ")";
    botAI->TellMaster(out);
}

uint32 ListQuestsAction::ListQuests(bool completed, bool silent, QuestTravelDetail travelDetail)
{
    TravelTarget* target;
    WorldPosition botPos(bot);
    if (travelDetail != QUEST_TRAVEL_DETAIL_NONE)
        target = context->GetValue<TravelTarget*>("travel target")->Get();

    uint32 count = 0;
    for (uint16 slot = 0; slot < MAX_QUEST_LOG_SIZE; ++slot)
    {
        uint32 questId = bot->GetQuestSlotQuestId(slot);
        if (!questId)
            continue;

        Quest const* pQuest = sObjectMgr->GetQuestTemplate(questId);
        bool isCompletedQuest = bot->GetQuestStatus(questId) == QUEST_STATUS_COMPLETE;
        if (completed != isCompletedQuest)
            continue;

        ++count;

        if (silent)
            continue;

        botAI->TellMaster(chat->FormatQuest(pQuest));

        if (travelDetail != QUEST_TRAVEL_DETAIL_NONE && target->getDestination())
        {
            if (target->getDestination()->getName() == "QuestRelationTravelDestination" ||
                target->getDestination()->getName() == "QuestObjectiveTravelDestination")
            {
                QuestTravelDestination* QuestDestination = (QuestTravelDestination*)target->getDestination();

                if (QuestDestination->GetQuestTemplate()->GetQuestId() == questId)
                {
                    std::ostringstream out;
                    out << "[Active] traveling " << target->getPosition()->distance(botPos);
                    out << " to " << QuestDestination->getTitle();
                    botAI->TellMaster(out);
                }
            }
        }

        if (travelDetail == QUEST_TRAVEL_DETAIL_SUMMARY)
        {
            std::vector<TravelDestination*> allDestinations =
                sTravelMgr->getQuestTravelDestinations(bot, questId, true, true, -1);
            std::vector<TravelDestination*> availDestinations =
                sTravelMgr->getQuestTravelDestinations(bot, questId, botAI->GetMaster(), false, -1);

            uint32 desTot = allDestinations.size();
            uint32 desAvail = availDestinations.size();
            uint32 desFull = desAvail - sTravelMgr->getQuestTravelDestinations(bot, questId, false, false, -1).size();
            uint32 desRange = desAvail - sTravelMgr->getQuestTravelDestinations(bot, questId, false, false).size();

            uint32 tpoints = 0;
            uint32 apoints = 0;

            for (auto dest : allDestinations)
                tpoints += dest->getPoints(true).size();

            for (auto dest : availDestinations)
                apoints += dest->getPoints().size();

            std::ostringstream out;
            out << desAvail << "/" << desTot << " destinations " << apoints << "/" << tpoints << " points. ";

            if (desFull > 0)
                out << desFull << " crowded.";

            if (desRange > 0)
                out << desRange << " out of range.";

            botAI->TellMaster(out);
        }
        else if (travelDetail == QUEST_TRAVEL_DETAIL_FULL)
        {
            uint32 limit = 0;
            std::vector<TravelDestination*> allDestinations =
                sTravelMgr->getQuestTravelDestinations(bot, questId, true, true, -1);

            std::sort(allDestinations.begin(), allDestinations.end(),
                      [botPos](TravelDestination* i, TravelDestination* j) {
                          return i->distanceTo(const_cast<WorldPosition*>(&botPos)) <
                                 j->distanceTo(const_cast<WorldPosition*>(&botPos));
                      });

            for (auto dest : allDestinations)
            {
                if (limit > 5)
                    continue;

                std::ostringstream out;

                uint32 tpoints = dest->getPoints(true).size();
                uint32 apoints = dest->getPoints().size();

                out << round(dest->distanceTo(const_cast<WorldPosition*>(&botPos)));
                out << " to " << dest->getTitle();
                out << " " << apoints;

                if (apoints < tpoints)
                    out << "/" << tpoints;

                out << " points.";

                if (!dest->isActive(bot))
                    out << " not active";

                if (dest->isFull(bot))
                    out << " crowded";

                botAI->TellMaster(out);

                limit++;
            }
        }
    }

    return count;
}

void ListQuestsAction::ListQuestsWithProgress()
{
    botAI->TellMaster("--- Quest Progress ---");

    uint32 incompleteCount = 0;
    uint32 completeCount = 0;

    for (uint16 slot = 0; slot < MAX_QUEST_LOG_SIZE; ++slot)
    {
        uint32 questId = bot->GetQuestSlotQuestId(slot);
        if (!questId)
            continue;

        Quest const* questTemplate = sObjectMgr->GetQuestTemplate(questId);
        if (!questTemplate)
            continue;

        bool isComplete = bot->GetQuestStatus(questId) == QUEST_STATUS_COMPLETE;

        if (isComplete)
        {
            completeCount++;
            std::ostringstream out;
            out << chat->FormatQuest(questTemplate) << " - |c0000FF00COMPLETE|r";
            botAI->TellMaster(out);
        }
        else
        {
            incompleteCount++;
            // Show quest name
            botAI->TellMaster(chat->FormatQuest(questTemplate));

            // Show objectives with progress
            QuestStatusData questStatus = bot->getQuestStatusMap()[questId];

            for (uint32 i = 0; i < QUEST_OBJECTIVES_COUNT; i++)
            {
                // Item objectives (collect X items)
                if (questTemplate->RequiredItemId[i])
                {
                    uint32 required = questTemplate->RequiredItemCount[i];
                    uint32 available = questStatus.ItemCount[i];
                    ItemTemplate const* proto = sObjectMgr->GetItemTemplate(questTemplate->RequiredItemId[i]);
                    if (proto)
                    {
                        botAI->TellMaster(chat->FormatQuestObjective(chat->FormatItem(proto), available, required));
                    }
                }

                // NPC/GO objectives (kill X creatures or interact with objects)
                if (questTemplate->RequiredNpcOrGo[i])
                {
                    uint32 required = questTemplate->RequiredNpcOrGoCount[i];
                    uint32 available = questStatus.CreatureOrGOCount[i];

                    if (questTemplate->RequiredNpcOrGo[i] < 0)
                    {
                        // Game Object
                        if (GameObjectTemplate const* info = sObjectMgr->GetGameObjectTemplate(-questTemplate->RequiredNpcOrGo[i]))
                        {
                            botAI->TellMaster(chat->FormatQuestObjective(info->name, available, required));
                        }
                    }
                    else
                    {
                        // Creature
                        if (CreatureTemplate const* info = sObjectMgr->GetCreatureTemplate(questTemplate->RequiredNpcOrGo[i]))
                        {
                            botAI->TellMaster(chat->FormatQuestObjective(info->Name, available, required));
                        }
                    }
                }
            }
        }
    }

    std::ostringstream summary;
    summary << "--- Total: " << (completeCount + incompleteCount) << " quests ("
            << incompleteCount << " in progress, " << completeCount << " ready to turn in) ---";
    botAI->TellMaster(summary);
}
