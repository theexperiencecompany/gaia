import type { IMessage } from "@/lib/db/chatDb";

/** A message as stored before reactions became a field: a reaction was its own `emoji_ack` bot message. */
export type LegacyStoredMessage = IMessage & {
  kind?: string | null;
  reacts_to_message_id?: string | null;
};

const LEGACY_ACK_KIND = "emoji_ack";

const withoutAckStamp = ({
  kind: _kind,
  reacts_to_message_id: _target,
  ...message
}: LegacyStoredMessage): IMessage => message;

/**
 * Fold cached `emoji_ack` messages into the reaction field of the user message
 * they answered, the same rule the server's migration applies: an ack with cards
 * stays with no text, one without is removed, one whose target is gone stays as text.
 */
export function foldLegacyReactionAcks(messages: LegacyStoredMessage[]): {
  updated: IMessage[];
  removedIds: string[];
} {
  const byId = new Map(messages.map((message) => [message.id, message]));
  const updated = new Map<string, IMessage>();
  const removedIds: string[] = [];
  for (const ack of messages) {
    if (ack.kind !== LEGACY_ACK_KIND) continue;
    const emoji = ack.content.trim();
    const target = ack.reacts_to_message_id
      ? byId.get(ack.reacts_to_message_id)
      : undefined;
    if (!emoji || !target || target.role !== "user") {
      updated.set(ack.id, withoutAckStamp(ack));
      continue;
    }
    const current = updated.get(target.id) ?? target;
    updated.set(target.id, {
      ...current,
      reaction: { emoji, by: "chat_model" },
    });
    if (ack.tool_data?.length) {
      updated.set(ack.id, { ...withoutAckStamp(ack), content: "" });
    } else {
      removedIds.push(ack.id);
    }
  }
  return { updated: [...updated.values()], removedIds };
}
