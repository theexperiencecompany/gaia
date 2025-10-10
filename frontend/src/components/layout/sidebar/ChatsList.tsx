"use client";

import { isToday, isYesterday, subDays } from "date-fns";
import { Loader } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/shadcn/accordion";
import { Conversation } from "@/features/chat/api/chatApi";
import {
  useConversationList,
  useFetchConversations,
} from "@/features/chat/hooks/useConversationList";

import { ChatTab } from "./ChatTab";

// Reusable accordion item styles
const accordionItemStyles = {
  item: "my-1 flex min-h-fit w-full flex-col items-start justify-start overflow-hidden border-none py-1",
  trigger:
    "w-full px-2 pt-0 pb-1 text-xs text-foreground-400 hover:no-underline hover:text-foreground-500",
  content: "w-full p-0!",
  chatContainer: "flex w-full flex-col",
};

const getTimeFrame = (dateString: string): string => {
  const date = new Date(dateString);

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
  const { conversations, paginationMeta } = useConversationList();
  const fetchConversations = useFetchConversations();
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [isFetchingMore, setIsFetchingMore] = useState(false);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  // We assume the provider auto-fetches the first page.
  // Once paginationMeta is available, we consider the initial load complete.
  useEffect(() => {
    if (paginationMeta) setLoading(false);
  }, [paginationMeta]);

  // Set up an IntersectionObserver to load more pages.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];

        if (
          entry.isIntersecting &&
          !isFetchingMore &&
          paginationMeta &&
          currentPage < paginationMeta.total_pages
        ) {
          setIsFetchingMore(true);
          // Always use a fixed limit (e.g. 10) and always append new results.
          fetchConversations(currentPage + 1, 20, true)
            .then(() => {
              setCurrentPage((prevPage) => prevPage + 1);
            })
            .catch((error) => {
              console.error("Failed to fetch more conversations", error);
            })
            .finally(() => {
              setIsFetchingMore(false);
            });
        }
      },
      {
        root: null,
        threshold: 1.0,
      },
    );

    const currentLoadMoreRef = loadMoreRef.current;

    if (currentLoadMoreRef) observer.observe(currentLoadMoreRef);

    return () => {
      if (currentLoadMoreRef) observer.unobserve(currentLoadMoreRef);
    };
  }, [currentPage, isFetchingMore, paginationMeta, fetchConversations]);

  // Separate system-generated conversations using the new flags
  const systemConversations = conversations.filter(
    (conversation) => conversation.is_system_generated === true,
  );

  // Regular conversations (excluding system-generated ones)
  const regularConversations = conversations.filter(
    (conversation) => conversation.is_system_generated !== true,
  );

  // Group regular conversations by time frame.
  const groupedConversations = regularConversations.reduce(
    (acc, conversation) => {
      const timeFrame = getTimeFrame(conversation.createdAt);

      if (!acc[timeFrame]) {
        acc[timeFrame] = [];
      }
      acc[timeFrame].push(conversation);

      return acc;
    },
    {} as Record<string, Conversation[]>,
  );

  // Sort time frames by defined priority.
  const sortedTimeFrames = Object.entries(groupedConversations).sort(
    ([timeFrameA], [timeFrameB]) =>
      timeFramePriority(timeFrameA) - timeFramePriority(timeFrameB),
  );

  const starredConversations = regularConversations.filter(
    (conversation) => conversation.starred,
  );

  // Calculate which accordions should be open by default - show ALL expanded
  const getDefaultAccordionValues = () => {
    const defaultValues: string[] = [];

    // Add system conversations if they exist
    if (systemConversations.length > 0) {
      defaultValues.push("system-conversations");
    }

    // Add starred chats if they exist
    if (starredConversations.length > 0) {
      defaultValues.push("starred-chats");
    }

    // Add ALL time frame sections - show everything expanded by default
    const timeFrameValues = sortedTimeFrames.map(([timeFrame]) =>
      timeFrame.toLowerCase().replace(/\s+/g, "-"),
    );
    defaultValues.push(...timeFrameValues);

    return defaultValues;
  };

  return (
    <>
      {loading ? (
        <div className="flex items-center justify-center p-10">
          <Loader className="animate-spin text-[#00bbff]" />
        </div>
      ) : (
        <Accordion
          type="multiple"
          className="w-full p-0"
          defaultValue={getDefaultAccordionValues()}
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
                      (a: Conversation, b: Conversation) =>
                        new Date(b.createdAt).getTime() -
                        new Date(a.createdAt).getTime(),
                    )
                    .map((conversation: Conversation) => (
                      <ChatTab
                        key={conversation.conversation_id}
                        id={conversation.conversation_id}
                        name={conversation.description || "System Actions"}
                        starred={conversation.starred || false}
                        isSystemGenerated={
                          conversation.is_system_generated || false
                        }
                        systemPurpose={conversation.system_purpose}
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
                  {starredConversations.map((conversation: Conversation) => (
                    <ChatTab
                      key={conversation.conversation_id}
                      id={conversation.conversation_id}
                      name={conversation.description || "New chat"}
                      starred={conversation.starred || false}
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
                      (a: Conversation, b: Conversation) =>
                        new Date(b.createdAt).getTime() -
                        new Date(a.createdAt).getTime(),
                    )
                    .map((conversation: Conversation, index: number) => (
                      <ChatTab
                        key={index}
                        id={conversation.conversation_id}
                        name={conversation.description || "New chat"}
                        starred={conversation.starred}
                      />
                    ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}

      {/* Sentinel element for the IntersectionObserver */}
      <div
        ref={loadMoreRef}
        className="flex h-[50px] items-center justify-center p-2"
      >
        {isFetchingMore && <Loader className="animate-spin text-[#00bbff]" />}
      </div>
    </>
  );
}
