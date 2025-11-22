"use client";

import { isToday, isYesterday, subDays } from "date-fns";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import {
  useConversationList,
  useFetchConversations,
} from "@/features/chat/hooks/useConversationList";
import { Watch02Icon } from '@/icons';
import type { IConversation } from "@/lib/db/chatDb";

import { ChatTab } from "./ChatTab";
import { accordionItemStyles } from "./constants";

const getTimeFrame = (date: Date): string => {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";

  const daysAgo7 = subDays(new Date(), 7);
  const daysAgo30 = subDays(new Date(), 30);

  if (date >= daysAgo7) return "Previous 7 days";
  if (date >= daysAgo30) return "Previous 30 days";

  return "All time";
};

const timeFramePriority = (timeFrame: string): number => {
  switch (timeFrame) {
    case "Today":
      return 0;
    case "Yesterday":
      return 1;
    case "Previous 7 days":
      return 2;
    case "Previous 30 days":
      return 3;
    case "All time":
      return 4;
    default:
      return 5;
  }
};

export default function ChatsList() {
  const {
    conversations: apiConversations,
    loading,
    error,
  } = useConversationList();
  const fetchConversations = useFetchConversations();
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    console.log("[ChatsList] useEffect triggered:", {
      conversationsCount: apiConversations.length,
      loading,
      hasFetched: hasFetchedRef.current,
      conversations: apiConversations.map((c) => ({
        id: c.conversation_id,
        desc: c.description,
      })),
    });

    // Only fetch once on initial mount if store is empty
    if (!hasFetchedRef.current && apiConversations.length === 0 && !loading) {
      console.log("[ChatsList] Fetching conversations because store is empty");
      hasFetchedRef.current = true;
      fetchConversations(1, 20, false);
    }
  }, [apiConversations.length, loading, fetchConversations]);

  const conversations: IConversation[] = useMemo(() => {
    return apiConversations.map((conv) => ({
      id: conv.conversation_id,
      title: conv.description || "Untitled conversation",
      description: conv.description,
      userId: conv.user_id,
      starred: conv.starred ?? false,
      isSystemGenerated: conv.is_system_generated ?? false,
      systemPurpose: conv.system_purpose ?? null,
      createdAt: new Date(conv.createdAt),
      updatedAt: conv.updatedAt
        ? new Date(conv.updatedAt)
        : new Date(conv.createdAt),
    }));
  }, [apiConversations]);

  const { systemConversations, starredConversations, sortedTimeFrames } =
    useMemo(() => {
      const system = conversations.filter(
        (conversation) => conversation.isSystemGenerated === true,
      );

      const regular = conversations.filter(
        (conversation) => conversation.isSystemGenerated !== true,
      );

      const starred = regular.filter((conversation) => conversation.starred);

      const grouped = regular.reduce(
        (acc, conversation) => {
          const timeFrame = getTimeFrame(conversation.createdAt);

          if (!acc[timeFrame]) {
            acc[timeFrame] = [];
          }
          acc[timeFrame].push(conversation);

          return acc;
        },
        {} as Record<string, IConversation[]>,
      );

      const sorted = Object.entries(grouped).sort(
        ([timeFrameA], [timeFrameB]) =>
          timeFramePriority(timeFrameA) - timeFramePriority(timeFrameB),
      );

      return {
        systemConversations: system,
        starredConversations: starred,
        sortedTimeFrames: sorted,
      };
    }, [conversations]);

  const isLoading = loading;
  const isError = !!error;

  // Calculate which accordions should be open - controlled state
  const getAccordionValues = () => {
    const values: string[] = [];

    // Add system conversations if they exist
    if (systemConversations.length > 0) {
      values.push("system-conversations");
    }

    // Add starred chats if they exist
    if (starredConversations.length > 0) {
      values.push("starred-chats");
    }

    // Add ALL time frame sections - show everything expanded
    const timeFrameValues = sortedTimeFrames.map(([timeFrame]) =>
      timeFrame.toLowerCase().replace(/\s+/g, "-"),
    );
    values.push(...timeFrameValues);

    return values;
  };

  // Use controlled state for accordion values that updates with conversations
  const [openAccordions, setOpenAccordions] = useState<string[]>([]);

  // Update open accordions whenever conversations change
  useEffect(() => {
    setOpenAccordions(getAccordionValues());
  }, [
    systemConversations.length,
    starredConversations.length,
    sortedTimeFrames.length,
  ]);

  return (
    <>
      {isLoading && conversations.length === 0 ? (
        <div className="flex items-center justify-center p-10">
          <Watch02Icon className="animate-spin text-[#00bbff]" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center gap-2 p-6 text-center">
          <p className="text-sm text-foreground-500">
            We couldn&apos;t load your conversations. Please try again.
          </p>
        </div>
      ) : (
        <Accordion
          type="multiple"
          className="w-full p-0"
          value={openAccordions}
          onValueChange={setOpenAccordions}
        >
          {/* System-generated conversations */}
          {systemConversations.length > 0 && (
            <AccordionItem
              value="system-conversations"
              className={accordionItemStyles.item}
            >
              <AccordionTrigger className={accordionItemStyles.trigger}>
                Created by GAIA
              </AccordionTrigger>
              <AccordionContent className={accordionItemStyles.content}>
                <div className={accordionItemStyles.chatContainer}>
                  {systemConversations
                    .sort(
                      (a: IConversation, b: IConversation) =>
                        b.createdAt.getTime() - a.createdAt.getTime(),
                    )
                    .map((conversation: IConversation) => (
                      <ChatTab
                        key={conversation.id}
                        id={conversation.id}
                        name={conversation.title || "System Actions"}
                        starred={conversation.starred ?? false}
                        isSystemGenerated={
                          conversation.isSystemGenerated ?? false
                        }
                        systemPurpose={conversation.systemPurpose ?? undefined}
                      />
                    ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {/* Starred conversations */}
          {starredConversations.length > 0 && (
            <AccordionItem
              value="starred-chats"
              className={accordionItemStyles.item}
            >
              <AccordionTrigger className={accordionItemStyles.trigger}>
                Starred Chats
              </AccordionTrigger>
              <AccordionContent className={accordionItemStyles.content}>
                <div className="-mr-4 flex w-full flex-col">
                  {starredConversations.map((conversation: IConversation) => (
                    <ChatTab
                      key={conversation.id}
                      id={conversation.id}
                      name={conversation.title || "New chat"}
                      starred={conversation.starred ?? false}
                    />
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {/* Grouped Conversations by Time Frame */}
          {sortedTimeFrames.map(([timeFrame, conversationsGroup]) => (
            <AccordionItem
              key={timeFrame}
              value={timeFrame.toLowerCase().replace(/\s+/g, "-")}
              className={accordionItemStyles.item}
            >
              <AccordionTrigger className={accordionItemStyles.trigger}>
                {timeFrame}
              </AccordionTrigger>
              <AccordionContent className={accordionItemStyles.content}>
                <div className={accordionItemStyles.chatContainer}>
                  {conversationsGroup
                    .sort(
                      (a: IConversation, b: IConversation) =>
                        b.createdAt.getTime() - a.createdAt.getTime(),
                    )
                    .map((conversation: IConversation) => (
                      <ChatTab
                        key={conversation.id}
                        id={conversation.id}
                        name={conversation.title || "New chat"}
                        starred={conversation.starred ?? false}
                      />
                    ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
    </>
  );
}
