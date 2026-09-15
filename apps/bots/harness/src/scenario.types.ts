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
}

/** One inbound message and the assertions on the reply it produces. */
export interface ScenarioTurn {
  /** The message to inject as the scenario user. */
  send: string;
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
