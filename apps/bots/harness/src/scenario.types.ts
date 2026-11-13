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
}

/** One message of a {@link ScenarioTurn.burst}. */
export interface BurstMessage {
  send: string;
  /** Milliseconds after the previous message of the burst arrived (0 for the first). */
  afterMs?: number;
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
   * replies; the turn ends once every one has been handled. The emulated
   * platform decides whether they are handled one at a time.
   */
  burst?: BurstMessage[];
  /** Optional channel/conversation id (defaults to the user's platform id). */
  channelId?: string;
  /** Assertions on the transcript this turn generated. */
  expect?: ScenarioAssertion[];
  /**
   * Milliseconds to keep the outbound consumer alive after the reply stream
   * closes, so this turn's proactive deliveries land in ITS events. Overrides
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
  /** Ordered conversation turns. */
  turns: ScenarioTurn[];
  /**
   * Default settle window for every turn, in milliseconds (0 = don't wait). A
   * handoff reply closes its SSE stream on the preamble while the real answer
   * publishes to the outbound queue seconds later; without settling, the answer
   * lands in a later `gaia-sim` boot's unrelated transcript instead of this one.
   */
  settleMs?: number;
}
