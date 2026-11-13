import type { IMessage } from "@/lib/db/chatDb";

/** The backend message kind of a turn that handed work off and said nothing. */
export const ACCEPTED_MESSAGE_KIND = "accepted";

const SILENT_KINDS = new Set<string | undefined>([
  ACCEPTED_MESSAGE_KIND,
  "emoji_ack",
]);

/**
 * Whether the work an accepted turn started has produced an answer: a later
 * assistant message with words in it. The result lands in the conversation that
 * asked, so this reads the same live (an `outbox.message` arrives) and after a
 * reload.
 */
export function isWorkAnswered(
  messages: IMessage[],
  acceptedMessageId: string,
): boolean {
  const index = messages.findIndex((m) => m.id === acceptedMessageId);
  if (index === -1) return false;
  return messages
    .slice(index + 1)
    .some(
      (m) =>
        m.role === "assistant" &&
        m.content.trim().length > 0 &&
        !SILENT_KINDS.has(m.kind ?? undefined),
    );
}
