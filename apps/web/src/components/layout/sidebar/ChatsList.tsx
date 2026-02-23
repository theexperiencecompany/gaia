"use client";

import { isToday, isYesterday, subDays } from "date-fns";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import Spinner from "@/components/ui/spinner";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { useInfiniteConversations } from "@/features/chat/hooks/useInfiniteConversations";
import { useSyncStatus } from "@/hooks/useBackgroundSync";
import { cn } from "@/lib";
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
  const { conversations: apiConversations } = useConversationList();
  const { initialSyncCompleted } = useSyncStatus();
  const { loadMoreConversations, isLoadingMore, hasMore, totalPages } =
    useInfiniteConversations();

  // Sentinel element ref for IntersectionObserver
  const sentinelRef = useRef<HTMLDivElement>(null);

  const conversations: IConversation[] = useMemo(() => {
    return apiConversations.map((conv) => ({
      id: conv.conversation_id,
      title: conv.description || "Untitled conversation",
      description: conv.description,
      userId: conv.user_id,
      starred: conv.starred ?? false,
      isSystemGenerated: conv.is_system_generated ?? false,
      systemPurpose: conv.system_purpose ?? null,
      isUnread: conv.is_unread ?? false,
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

  // Show loading only when there are no cached conversations and hydration hasn't completed
  const isLoading = conversations.length === 0 && !initialSyncCompleted;

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

  // Direct scroll listener for infinite scroll - throttled with requestAnimationFrame
  useEffect(() => {
    // Skip if still loading (sentinel not rendered yet)
    if (isLoading) return;

    // Find the scrollable parent (SidebarContent with overflow-auto)
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    let scrollContainer: HTMLElement | null = sentinel.parentElement;
    while (scrollContainer) {
      const style = window.getComputedStyle(scrollContainer);
      if (style.overflowY === "auto" || style.overflowY === "scroll") {
        break;
      }
      scrollContainer = scrollContainer.parentElement;
    }

    if (!scrollContainer) return;

    let ticking = false;

    const handleScroll = () => {
      if (ticking) return;

      ticking = true;
      requestAnimationFrame(() => {
        const { scrollTop, scrollHeight, clientHeight } = scrollContainer!;
        const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

        if (distanceFromBottom < 100 && hasMore && !isLoadingMore) {
          loadMoreConversations();
        }
        ticking = false;
      });
    };

    scrollContainer.addEventListener("scroll", handleScroll, { passive: true });

    // Check immediately in case we're already near bottom
    handleScroll();

    return () => {
      scrollContainer?.removeEventListener("scroll", handleScroll);
    };
  }, [
    isLoading,
    hasMore,
    isLoadingMore,
    loadMoreConversations,
    conversations.length,
  ]);

  return (
    <>
      {isLoading ? (
        <div className="flex items-center justify-center p-10">
          <Spinner />
        </div>
      ) : (
        <>
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
                <AccordionTrigger
                  className={cn(
                    accordionItemStyles.trigger,
                    "hover:text-zinc-500",
                  )}
                >
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
                          systemPurpose={
                            conversation.systemPurpose ?? undefined
                          }
                          isUnread={conversation.isUnread ?? false}
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
                <AccordionTrigger
                  className={cn(
                    accordionItemStyles.trigger,
                    "hover:text-zinc-500",
                  )}
                >
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
                        isUnread={conversation.isUnread ?? false}
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
                <AccordionTrigger
                  className={cn(
                    accordionItemStyles.trigger,
                    "hover:text-zinc-500",
                  )}
                >
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
                          isUnread={conversation.isUnread ?? false}
                        />
                      ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>

          {/* Sentinel element for IntersectionObserver - detects when user scrolls near bottom */}
          <div ref={sentinelRef} className="h-1" aria-hidden="true" />

          {/* Loading indicator for infinite scroll */}
          {isLoadingMore && (
            <div className="flex items-center justify-center py-4">
              <Spinner />
            </div>
          )}

          {/* End of list indicator - only show when there were multiple pages */}
          {!hasMore && totalPages > 1 && conversations.length > 0 && (
            <div className="py-4 text-center text-xs text-zinc-500">
              You&apos;re all caught up
            </div>
          )}
        </>
      )}
    </>
  );
}
