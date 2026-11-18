/**
 * Schema for `gaia-sim run <scenario.yaml>` files: a multi-turn conversation
 * plus transcript assertions checked against the recorded events.
 */

import type { PlatformName } from "@gaia/shared/bots";

/** Assertions checked against the transcript events a single turn produced. */
export interface ScenarioAssertion {
  /** Exact number of delivered `send` bubbles (a new message each). */
  bubbleCount?: number;
  /** Lower bound on delivered `send` bubbles. */
  minBubbles?: number;
  /** At least one delivered bubble/ephemeral text contains this substring. */
  contains?: string;
  /** Every delivered bubble's rendered length is ≤ this (the platform limit). */
  maxBubbleLength?: number;
  /** The turn's transcript contains at least one event of each listed type. */
  eventTypes?: string[];
  /**
   * Everything the turn delivered, in the order it first appeared: entry N is a
   * substring of the Nth delivered message's final text (a bubble after its
   * last edit, a proactive delivery, an attachment's caption), and the counts
   * are equal.
   */
  delivered?: string[];
  /**
   * {@link delivered} for the bubbles the turn's replies opened alone, without
   * proactive deliveries — whose place among the replies can depend on timing.
   */
  bubbles?: string[];
  /**
   * Exactly which of the turn's inbound messages received a reaction, by their
   * 1-based position in the turn (a burst's order). `[]` asserts none did.
   */
  reactedTo?: number[];
  /**
   * Which inbound message each bubble quotes, by the bubble's text: a key is a
   * substring of one bubble's final text, its value the 1-based position (in
   * the turn) of the inbound message that bubble replies to, or null for a
   * bubble that quotes nothing.
   */
  quotes?: Record<string, number | null>;
  /** True: no bubble was deleted or edited to shorter text — nothing shown was taken back. */
  noTakeBacks?: boolean;
  /** No delivered message's final text contains any of these substrings. */
  excludes?: string[];
}

/** One message of a {@link ScenarioTurn.burst}. */
export interface BurstMessage {
  send: string;
  /** Milliseconds after the previous message of the burst arrived (0 for the first). */
  afterMs?: number;
}

/** A platform outage: the next `failures` sends and edits fail with this HTTP status, then it answers again. */
export interface PlatformOutage {
  failures: number;
  /** A transient status the platform answers with: 429, 500, 502, 503 or 504. */
  status: number;
}

/**
 * One inbound message, or a burst of them, and the assertions on what the turn
 * produced. Exactly one of `send` and `burst` is set.
 */
export interface ScenarioTurn {
  /** The message to inject as the scenario user. */
  send?: string;
  /**
   * Messages that arrive at the given gaps without waiting for each other's
   * replies; each is posted at once, and the turn ends once the conversation
   * is idle with every reply shown.
   */
  burst?: BurstMessage[];
  /** Optional channel/conversation id (defaults to the user's platform id). */
  channelId?: string;
  /** The platform fails this turn's first sends and edits, as Telegram does in an outage. */
  outage?: PlatformOutage;
  /**
   * The bot process restarts the moment it has sent this many messages in the
   * turn: the running bot stops with that bubble still streaming, and a fresh
   * one boots and resumes. Counted on the reply, not the clock, so a faster or
   * slower start to the reply cannot move the restart outside a bubble.
   */
  restartAfterSends?: number;
  /** Assertions on the transcript this turn generated. */
  expect?: ScenarioAssertion[];
  /**
   * Milliseconds to keep the outbound consumer alive after the conversation
   * goes idle, so this turn's proactive deliveries land in ITS events. Overrides
   * the scenario-level {@link Scenario.settleMs}. See that field for why.
   */
  settleMs?: number;
}

/** A complete scenario: which platform + user, and the ordered turns. */
export interface Scenario {
  /** Human-readable scenario name (used in reporting). */
  name: string;
  emulate: PlatformName;
  /** Email of the dev user to mint + link (via the dev endpoints). */
  user: string;
  /** Tools GAIA asks before calling for this user; unset or empty asks before none. */
  askBefore?: string[];
  /** Ordered conversation turns. */
  turns: ScenarioTurn[];
  /**
   * Default settle window for every turn, in milliseconds (0 = don't wait).
   * Replies and work results arrive on the conversation's events stream and are
   * waited for already; settling keeps the outbound consumer alive for what still
   * comes through the queue (workflow and todo deliveries, approval prompts),
   * which would otherwise land in a later `gaia-sim` boot's transcript.
   */
  settleMs?: number;
}
