/**
 * Fold comms REACT acks onto their target messages for render.
 *
 * A background emoji-ack arrives (and persists) as its own message with
 * `kind: "emoji_ack"` + `reacts_to_message_id`. Rendering it as a bubble
 * would show a stray giant glyph; instead the ack's emoji attaches to the
 * target message's `reactions` and the ack itself is dropped from the render
 * list. The stored records are untouched — folding is pure and re-runnable,
 * so reload, sync, and live push all converge on the same view.
 *
 * An ack whose target is absent (not loaded, another conversation, or no
 * target at all) stays a normal message — the pre-reaction bubble behavior —
 * so the acknowledgment is never lost. Folding is idempotent: re-running over
 * already-folded output changes nothing.
 *
 * Web (`IMessage.content`) and mobile (`Message.text`) carry the ack glyph
 * under different keys, so the text is read through `getText` and the fold
 * stays generic over both shapes.
 */

/** One emoji reaction attached to a message for render. `ackId` dedups re-syncs. */
export interface ReactionBadge {
  emoji: string;
  ackId: string;
}

/** The fields folding reads and writes. Both app message shapes satisfy this. */
export interface ReactionFoldable {
  id: string;
  messageId?: string | null;
  kind?: string | null;
  reacts_to_message_id?: string | null;
  reactions?: ReactionBadge[] | null;
}

export function isReactionAck<T extends ReactionFoldable>(
  message: T,
  getText: (message: T) => string,
): boolean {
  return message.kind === "emoji_ack" && getText(message).trim().length > 0;
}

export function foldReactionAcks<T extends ReactionFoldable>(
  messages: T[],
  getText: (message: T) => string,
): T[] {
  const acks = messages.filter((message) => isReactionAck(message, getText));
  if (acks.length === 0) return messages;

  const byId = new Map<string, T>();
  for (const message of messages) {
    byId.set(message.id, message);
    if (message.messageId && message.messageId !== message.id) {
      byId.set(message.messageId, message);
    }
  }

  const foldedAckIds = new Set<string>();
  const reactionsByTarget = new Map<string, ReactionBadge[]>();
  for (const ack of acks) {
    const targetId = ack.reacts_to_message_id;
    const target = (targetId && byId.get(targetId)) || undefined;
    if (!target || target.id === ack.id) continue;
    foldedAckIds.add(ack.id);
    const list = reactionsByTarget.get(target.id) ?? [];
    if (!list.some((reaction) => reaction.ackId === ack.id)) {
      list.push({ emoji: getText(ack), ackId: ack.id });
    }
    reactionsByTarget.set(target.id, list);
  }
  if (foldedAckIds.size === 0) return messages;

  return messages.flatMap((message) => {
    if (foldedAckIds.has(message.id)) return [];
    const extra = reactionsByTarget.get(message.id);
    if (!extra || extra.length === 0) return [message];
    const existing = message.reactions ?? [];
    const merged = [
      ...existing,
      ...extra.filter(
        (reaction) =>
          !existing.some((current) => current.ackId === reaction.ackId),
      ),
    ];
    if (merged.length === existing.length) return [message];
    return [{ ...message, reactions: merged }];
  });
}

/** One pill per distinct emoji, counting its reactions, in first-seen order. */
export function groupReactions(
  reactions: readonly Pick<ReactionBadge, "emoji">[],
): { emoji: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const { emoji } of reactions) {
    counts.set(emoji, (counts.get(emoji) ?? 0) + 1);
  }
  return [...counts].map(([emoji, count]) => ({ emoji, count }));
}
