/**
 * Two-phase dedupe for outbound messages, keyed on the outbox ledger's
 * `(outbox_message_id, part_index)`.
 *
 * RabbitMQ is at-least-once: a message redelivered after the platform already
 * accepted it would reach the user twice. A part is `claimed` when its send
 * starts (short TTL: an attempt that never finished stops blocking) and `sent`
 * once every bubble went out (long TTL: past the queue's own message TTL, so a
 * redelivery can never outlive the record of what it already did).
 *
 * The store lives in this process: one consumer per platform is the deployed
 * shape. It does not survive a restart, so a crash between the send and the ack
 * can still repeat that one message.
 */

/** How long an unfinished attempt blocks a redelivery of the same part. */
export const DEDUPE_CLAIMED_TTL_MS = 5 * 60 * 1000;

/** Longer than the API's default outbound queue TTL (24h) so no redelivery outlives it. */
export const DEDUPE_SENT_TTL_MS = 48 * 60 * 60 * 1000;

/** How often expired records are swept out, so the map stays bounded. */
const SWEEP_INTERVAL_MS = 60 * 1000;

export const DEDUPE_STATE = {
  CLAIMED: "claimed",
  SENT: "sent",
} as const;

export type DedupeState = (typeof DEDUPE_STATE)[keyof typeof DEDUPE_STATE];

interface DedupeRecord {
  state: DedupeState;
  expiresAt: number;
}

export class OutboundDedupeStore {
  private readonly records = new Map<string, DedupeRecord>();
  private lastSweepAt = 0;

  constructor(private readonly now: () => number = Date.now) {}

  /** The recorded state of a part, or undefined when it was never claimed or the record expired. */
  state(key: string): DedupeState | undefined {
    this.sweep();
    const record = this.records.get(key);
    if (!record || record.expiresAt <= this.now()) return undefined;
    return record.state;
  }

  claim(key: string): void {
    this.records.set(key, {
      state: DEDUPE_STATE.CLAIMED,
      expiresAt: this.now() + DEDUPE_CLAIMED_TTL_MS,
    });
  }

  markSent(key: string): void {
    this.records.set(key, {
      state: DEDUPE_STATE.SENT,
      expiresAt: this.now() + DEDUPE_SENT_TTL_MS,
    });
  }

  /** Forgets a claim whose attempt provably sent nothing, so a retry may send. */
  release(key: string): void {
    if (this.records.get(key)?.state === DEDUPE_STATE.CLAIMED) {
      this.records.delete(key);
    }
  }

  private sweep(): void {
    const now = this.now();
    if (now - this.lastSweepAt < SWEEP_INTERVAL_MS) return;
    this.lastSweepAt = now;
    for (const [key, record] of this.records) {
      if (record.expiresAt <= now) this.records.delete(key);
    }
  }
}

/** The dedupe key of one part of an outbox message. */
export function dedupeKey(outboxMessageId: string, partIndex: number): string {
  return `${outboxMessageId}:${partIndex}`;
}
