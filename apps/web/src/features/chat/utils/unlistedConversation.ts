import { isBotPlatform } from "@/config/botPlatforms";
import type { IConversation } from "@/lib/db/chatDb";

/**
 * A tracked todo's chat or a bot DM: reached from its own entry point, never in
 * the server's conversation list. Absent from that list means "not listed", not
 * "deleted", so sync asks about it by id and keeps it cached.
 */
export const isUnlistedConversation = (
  conversation: Pick<IConversation, "todoId" | "source">,
): boolean =>
  Boolean(conversation.todoId) ||
  (conversation.source != null && isBotPlatform(conversation.source));
