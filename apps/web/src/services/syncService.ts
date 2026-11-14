import { ConversationPageSchema } from "@shared/conversation";
import {
  type Conversation,
  type ConversationSyncItem,
  chatApi,
  type SyncedConversation,
} from "@/features/chat/api/chatApi";
import { MAX_SYNC_CONVERSATIONS } from "@/features/chat/constants";
import { applyConversationPage } from "@/features/chat/live/connection";
import {
  apiRowAwaitsApproval,
  isApprovalFlagStale,
} from "@/features/chat/utils/approvalFlag";
import type { RequestOrigin } from "@/lib/api/typed";
import { db, type IConversation } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { fromRegistryEntries } from "@/types/features/toolDataTypes";

const toTimestamp = (timestamp?: string): number => {
  if (!timestamp) return 0;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
};

/** Activity in the conversation on screen is already seen: mark it read on the server instead of lighting the dot. */
const unreadUnlessViewed = (conversation: SyncedConversation): boolean => {
  if (!conversation.is_unread) return false;
  const { conversation_id: conversationId } = conversation;
  if (useChatStore.getState().activeConversationId !== conversationId) {
    return true;
  }
  chatApi.markAsRead(conversationId).catch(console.error);
  return false;
};

const toStoredConversation = (
  conversation: SyncedConversation,
  artifacts: IConversation["artifacts"],
): IConversation => ({
  id: conversation.conversation_id,
  title: conversation.description || "Untitled conversation",
  description: conversation.description ?? "",
  starred: conversation.starred ?? false,
  isSystemGenerated: conversation.is_system_generated ?? false,
  systemPurpose: conversation.system_purpose ?? null,
  isUnread: unreadUnlessViewed(conversation),
  awaitingApproval: apiRowAwaitsApproval(conversation),
  todoId: conversation.todo_id ?? null,
  source: conversation.source ?? undefined,
  listed: conversation.listed,
  artifacts,
  createdAt: new Date(conversation.createdAt ?? 0),
  updatedAt: conversation.updatedAt
    ? new Date(conversation.updatedAt)
    : new Date(conversation.createdAt ?? 0),
});

const identifyStaleConversations = (
  localConversations: IConversation[],
  remoteConversations: Conversation[],
): ConversationSyncItem[] => {
  const localMap = new Map(
    localConversations.map((conv) => [
      conv.id,
      conv.updatedAt || conv.createdAt,
    ]),
  );
  const localFlagMap = new Map(
    localConversations.map((conv) => [conv.id, conv.awaitingApproval]),
  );

  const staleItems: ConversationSyncItem[] = [];

  for (const remote of remoteConversations) {
    const conversationId = remote.conversation_id;
    const localUpdatedAt = localMap.get(conversationId);

    if (!localUpdatedAt) {
      // New conversation not in local DB
      staleItems.push({
        conversation_id: conversationId,
        last_updated: undefined,
      });
      continue;
    }

    if (isApprovalFlagStale(localFlagMap.get(conversationId), remote)) {
      // Flag flipped without touching updatedAt — refetch for the dot.
      staleItems.push({
        conversation_id: conversationId,
        last_updated: localUpdatedAt.toISOString(),
      });
      continue;
    }

    const remoteUpdated = toTimestamp(
      remote.updatedAt ?? remote.createdAt ?? undefined,
    );
    const localUpdated = localUpdatedAt.getTime();

    if (remoteUpdated > localUpdated) {
      // Remote is newer than local
      staleItems.push({
        conversation_id: conversationId,
        last_updated: localUpdatedAt.toISOString(),
      });
    }
  }

  return staleItems;
};

/**
 * Identifies conversations that exist locally but were deleted on the server.
 * Applies safety filters to avoid aggressive deletion:
 * 1. Only considers conversations older than MIN_AGE_FOR_DELETION_MS
 * 2. Skips conversations that are currently being streamed
 * 3. Only checks against conversations within the sync window (first page of results)
 */
const identifyDeletedConversations = (
  localConversations: IConversation[],
  remoteConversations: Conversation[],
): string[] => {
  // Safety threshold: Only delete conversations that haven't been updated locally in the last X minutes
  // This prevents accidental deletion of conversations that might not be in the first page of API results
  // Reduced to 5 minutes to clean up deleted conversations faster while still providing a safety buffer for new creations
  const DELETED_CONVERSATION_SAFETY_MINUTES = 5;

  // Minimum age for a local conversation to be considered for deletion (in milliseconds)
  const MIN_AGE_FOR_DELETION_MS =
    DELETED_CONVERSATION_SAFETY_MINUTES * 60 * 1000;
  const remoteIds = new Set(remoteConversations.map((c) => c.conversation_id));
  const deletedIds: string[] = [];

  for (const local of localConversations) {
    // Skip if conversation exists on remote
    if (remoteIds.has(local.id)) continue;

    // An unlisted chat is never in the remote list, by design: absent there is not deleted.
    if (local.listed === false) continue;

    // Safety: Skip recently created/updated conversations
    // They might not have synced to the server yet, or might be beyond the pagination limit
    const localUpdateTime = (local.updatedAt || local.createdAt).getTime();
    const ageMs = Date.now() - localUpdateTime;

    if (ageMs < MIN_AGE_FOR_DELETION_MS) {
      continue;
    }

    deletedIds.push(local.id);
  }

  return deletedIds;
};

// DEBUG: surface cases where a sync merge would blank out or shrink an existing
// bot message's content — the symptom of a known overwrite bug.
export const batchSyncConversations = async (
  origin: RequestOrigin = {},
): Promise<void> => {
  try {
    const [remoteConversations, localConversations] = await Promise.all([
      chatApi
        .fetchConversations(1, MAX_SYNC_CONVERSATIONS, origin)
        .then((res) => res.conversations),
      db.getAllConversations(),
    ]);

    // An unlisted chat is never in the list, so only asking about it by id
    // shows a new message or its deletion. last_updated keeps the reply to what changed.
    const unlistedChatItems = localConversations.flatMap(
      (conv): ConversationSyncItem[] =>
        conv.listed === false
          ? [
              {
                conversation_id: conv.id,
                last_updated: (conv.updatedAt || conv.createdAt).toISOString(),
              },
            ]
          : [],
    );

    if (remoteConversations.length === 0 && unlistedChatItems.length === 0) {
      return;
    }

    const staleItems = [
      ...identifyStaleConversations(localConversations, remoteConversations),
      ...unlistedChatItems,
    ];

    // Identify conversations that exist locally but were deleted on the server
    const deletedConversationIds = identifyDeletedConversations(
      localConversations,
      remoteConversations,
    );

    if (deletedConversationIds.length > 0) {
      // Delete conversations that no longer exist on the server
      await db.deleteConversationsAndLogsBulk(deletedConversationIds);
    }

    if (staleItems.length === 0) {
      return;
    }

    const { conversations: freshConversations, missing } =
      await chatApi.batchSyncConversations(staleItems, origin);

    if (missing.length > 0) {
      await db.deleteConversationsAndLogsBulk(missing);
    }

    if (freshConversations.length === 0) {
      return;
    }

    await Promise.allSettled(
      freshConversations.map((conversation) =>
        applySyncedConversation(conversation.conversation_id, conversation),
      ),
    );
  } catch {
    // Ignore background sync errors to avoid impacting the UI
  }
};

/** Store a synced row's conversation fields and fold its newest page of entries into the live view. */
export const applySyncedConversation = async (
  conversationId: string,
  conversation: SyncedConversation,
): Promise<void> => {
  const artifacts = fromRegistryEntries(conversation.artifacts, conversationId);
  // Refresh the runtime lookup map from the server-authoritative registry. The
  // store stamps session_id onto each entry so artifact fetch URLs resolve.
  useChatStore.getState().setConversationArtifacts(conversationId, artifacts);
  await Promise.all([
    db.putConversation(toStoredConversation(conversation, artifacts)),
    applyConversationPage(
      conversationId,
      ConversationPageSchema.parse(conversation),
    ),
  ]);
};

/**
 * Sync a single conversation from backend to IndexedDB.
 * Used after stream cancellation to ensure local data matches backend.
 */
export const syncSingleConversation = async (
  conversationId: string,
): Promise<void> => {
  try {
    // Use batch sync with a single conversation item
    // Sending undefined for last_updated forces backend to return the full conversation
    const { conversations: freshConversations } =
      await chatApi.batchSyncConversations([
        { conversation_id: conversationId, last_updated: undefined },
      ]);

    if (freshConversations.length === 0) {
      return;
    }

    await applySyncedConversation(conversationId, freshConversations[0]);
  } catch (error) {
    console.error(
      `[SyncService] Failed to sync conversation ${conversationId}:`,
      error,
    );
  }
};
