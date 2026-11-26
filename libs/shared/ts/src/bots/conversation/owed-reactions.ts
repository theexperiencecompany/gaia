/**
 * The reactions a follow owes the platform, apart from its cursor: a reaction amends its
 * message at no seq of its own, so the server owes it until a report names it placed.
 */

import type { MessageReaction } from "../../api/generated";

export class OwedReactions {
  /** Owed emoji by user message id: logged, and not placed yet. */
  private readonly owed = new Map<string, MessageReaction[]>();
  /** Reactions settled since the last report. */
  private settled: MessageReaction[] = [];

  constructor(owed: readonly MessageReaction[]) {
    for (const reaction of owed) this.owe(reaction);
  }

  /** Hold a reaction as owed until it is settled, so a follow that ends before then hands it on. */
  owe(reaction: MessageReaction): void {
    const held = this.owed.get(reaction.message_id) ?? [];
    if (!held.some(({ emoji }) => emoji === reaction.emoji))
      this.owed.set(reaction.message_id, [...held, reaction]);
  }

  /** Whether the message has a reaction still owed. */
  has(messageId: string): boolean {
    return this.owed.has(messageId);
  }

  /** Settle every emoji owed on the message: what it shows now replaced the rest. */
  settle(messageId: string): void {
    const held = this.owed.get(messageId);
    if (!held) return;
    this.owed.delete(messageId);
    this.settled.push(...held);
  }

  /** Every reaction still owed. */
  get all(): MessageReaction[] {
    return [...this.owed.values()].flat();
  }

  /** The reactions settled since the last report, without taking them. */
  get unreported(): readonly MessageReaction[] {
    return this.settled;
  }

  /** Take the reactions settled since the last report, for the report being made. */
  takeUnreported(): MessageReaction[] {
    const taken = this.settled;
    this.settled = [];
    return taken;
  }
}
