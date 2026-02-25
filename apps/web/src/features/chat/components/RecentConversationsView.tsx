"use client";

import { Chip } from "@heroui/chip";
import { Calendar03Icon, MessageMultiple02Icon } from "@icons";
import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { useConversationList } from "@/features/chat/hooks/useConversationList";
import { useSyncStatus } from "@/hooks/useBackgroundSync";

const RecentConversationsView = memo(() => {
  const router = useRouter();
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

  const handleViewAll = useCallback(() => {
    router.push("/chat");
  }, [router]);

  return (
    <BaseCardView
      title="Recent Conversations"
      icon={<MessageMultiple02Icon className="h-6 w-6 text-zinc-500" />}
      isFetching={isLoading}
      isEmpty={displayConversations.length === 0 && !isLoading}
      emptyMessage="No recent conversations"
      errorMessage={syncError ?? undefined}
      path="/chat"
      onRefresh={handleViewAll}
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
