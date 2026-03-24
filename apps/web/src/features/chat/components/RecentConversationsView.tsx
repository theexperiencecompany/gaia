"use client";

import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import {
  BookOpen01Icon,
  Calendar03Icon,
  ChartLineData01Icon,
  HelpCircleIcon,
  MessageMultiple02Icon,
  PlayIcon,
} from "@icons";
import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";
import { DiscordIcon } from "@/components/shared/icons";
import type { CardAction } from "@/features/chat/components/interface/BaseCardView";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { useSyncStatus } from "@/hooks/useBackgroundSync";
import { useAppendToInput } from "@/stores/composerStore";

const RecentConversationsView = memo(() => {
  const router = useRouter();
  const appendToInput = useAppendToInput();
  const { conversations } = useConversationList();
  const { initialSyncCompleted, syncError } = useSyncStatus();

  // Only show loading when no cache AND initial sync hasn't completed
  const isLoading = conversations.length === 0 && !initialSyncCompleted;

  const displayConversations = useMemo(() => {
    return conversations.slice(0, 20);
  }, [conversations]);

  const handleConversationClick = useCallback(
    (conversationId: string) => {
      router.push(`/chat/${conversationId}`);
    },
    [router],
  );

  const actions: CardAction[] = useMemo(
    () => [
      {
        key: "catch-me-up",
        icon: <BookOpen01Icon className="size-4 text-zinc-400" />,
        label: "Catch me up",
        description:
          "Summarise key decisions and open questions from recent chats",
        onPress: () =>
          appendToInput(
            "Summarise my recent GAIA conversations. For each one, tell me the key decisions made, conclusions reached, and any open questions or unresolved items I should be aware of.",
          ),
      },
      {
        key: "unresolved",
        icon: <HelpCircleIcon className="size-4 text-zinc-400" />,
        label: "Find unresolved threads",
        description: "Identify conversations that ended with open action items",
        onPress: () =>
          appendToInput(
            "Go through my recent conversations and identify any that ended without a clear resolution — things where there were open action items, unanswered questions, or follow-ups I still need to do.",
          ),
      },
      {
        key: "themes",
        icon: <ChartLineData01Icon className="size-4 text-zinc-400" />,
        label: "What have we been working on?",
        description:
          "Identify recurring topics and patterns across recent chats",
        onPress: () =>
          appendToInput(
            "Look across my recent GAIA conversations and identify the main themes, recurring topics, and patterns. What have I been spending most of my time thinking about and working on?",
          ),
      },
      {
        key: "continue",
        icon: <PlayIcon className="size-4 text-zinc-400" />,
        label: "Continue where we left off",
        description: "Resume the most recent unfinished conversation",
        onPress: () =>
          appendToInput(
            "Look at my most recent GAIA conversation that had an unresolved question or unfinished task, give me a quick recap of where we were, and let's pick up from there.",
          ),
      },
    ],
    [appendToInput],
  );

  return (
    <BaseCardView
      title="Recent Conversations"
      icon={<MessageMultiple02Icon className="h-6 w-6 text-zinc-500" />}
      isFetching={isLoading}
      isEmpty={displayConversations.length === 0 && !isLoading}
      emptyMessage="No recent conversations"
      errorMessage={syncError ?? undefined}
      path="/chat"
      actions={actions}
    >
      <div className="space-y-0">
        {displayConversations.map((conversation) => (
          <div
            key={conversation.conversation_id}
            onClick={() =>
              handleConversationClick(conversation.conversation_id)
            }
            className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-zinc-700/30"
          >
            <div className="min-w-0 flex-1 flex justify-between">
              <div>
                <div className="flex items-start justify-between gap-2">
                  <h4 className="text-base font-medium text-white line-clamp-1">
                    {conversation.title}
                  </h4>
                  {conversation.starred && (
                    <span className="flex-shrink-0 text-yellow-500">★</span>
                  )}
                </div>
                {conversation.description && (
                  <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                    {conversation.description}
                  </p>
                )}
              </div>
              <div className="mt-2 flex items-center gap-1">
                <Chip
                  size="sm"
                  variant="flat"
                  className="text-zinc-400 px-1"
                  radius="sm"
                  startContent={
                    <MessageMultiple02Icon
                      width={15}
                      height={15}
                      className="mx-1"
                    />
                  }
                >
                  {conversation.messageCount}{" "}
                  {conversation.messageCount === 1 ? "message" : "messages"}
                </Chip>

                <Chip
                  size="sm"
                  variant="flat"
                  className="text-zinc-400 px-1"
                  radius="sm"
                  startContent={
                    <Calendar03Icon width={15} height={15} className="mx-1" />
                  }
                >
                  {new Date(conversation.updated_at).toLocaleDateString()}
                </Chip>

                {conversation.is_system_generated && (
                  <Tooltip
                    content="Auto-generated by GAIA"
                    showArrow
                    placement="top"
                    delay={0}
                    closeDelay={0}
                  >
                    <Chip
                      size="sm"
                      variant="flat"
                      className="text-zinc-400 px-1"
                      radius="sm"
                    >
                      <DiscordIcon width={13} height={13} color="#5865f2" />
                    </Chip>
                  </Tooltip>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </BaseCardView>
  );
});

RecentConversationsView.displayName = "RecentConversationsView";

export default RecentConversationsView;
