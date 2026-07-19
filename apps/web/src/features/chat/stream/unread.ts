import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";

/**
 * Whether the user is currently looking at this conversation. Derived from
 * location.pathname because it changes synchronously with navigation —
 * chatStore.activeConversationId only updates in a ChatPage effect and can lag
 * a stream close that races a navigation by a frame.
 */
export const isViewingConversation = (conversationId: string): boolean =>
  globalThis.location.pathname.includes(`/c/${conversationId}`);

/**
 * Surface a conversation as unread in the sidebar. Local write first for an
 * instant dot; the server flag second so the periodic conversation sync
 * (which mirrors remote is_unread) doesn't overwrite it with stale state.
 * Cleared by ChatPage's mark-as-read when the conversation is opened.
 */
export const markConversationUnread = (conversationId: string): void => {
  db.updateConversationFields(conversationId, { isUnread: true }).catch(
    (error) => {
      console.error("Failed to mark conversation unread locally:", error);
    },
  );
  chatApi.markAsUnread(conversationId).catch((error) => {
    console.error("Failed to mark conversation unread on server:", error);
  });
};
