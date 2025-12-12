"use client";

import { useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useRef } from "react";

import { BubbleConversationChatIcon } from "@/components";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import {
  useConversationList,
  useFetchConversations,
} from "@/features/chat/hooks/useConversationList";

const RecentConversationsView = memo(() => {
  const router = useRouter();
  const { conversations, loading, error } = useConversationList();
  const fetchConversations = useFetchConversations();
  const hasLoadedRef = useRef(false);

  useEffect(() => {
    if (!hasLoadedRef.current && conversations.length === 0 && !loading) {
      hasLoadedRef.current = true;
      fetchConversations(1, 10);
    }
  }, [conversations.length, loading, fetchConversations]);

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
      icon={<BubbleConversationChatIcon className="h-6 w-6 text-zinc-500" />}
      isFetching={loading}
      isEmpty={displayConversations.length === 0}
      emptyMessage="No recent conversations"
      errorMessage={error ?? "Failed to load conversations"}
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
            className="flex cursor-pointer items-center gap-3 p-3 transition-colors hover:bg-zinc-700/30"
          >
            <div className="min-w-0 flex-1">
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
            <div className="mt-1 text-xs text-zinc-500">
              {new Date(conversation.updated_at).toLocaleDateString()}
            </div>
          </div>
        ))}
      </div>
    </BaseCardView>
  );
});

RecentConversationsView.displayName = "RecentConversationsView";

export default RecentConversationsView;
