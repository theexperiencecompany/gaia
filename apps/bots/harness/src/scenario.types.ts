/**
 * Schema for `gaia-sim run <scenario.yaml>` files: a multi-turn conversation
 * plus transcript assertions checked against the recorded events.
 */

import type { PlatformName } from "@gaia/shared";

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
}

/** A complete scenario: which platform + user, and the ordered turns. */
export interface Scenario {
  /** Human-readable scenario name (used in reporting). */
  name: string;
  /** Platform to emulate. */
  emulate: PlatformName;
  /** Email of the dev user to mint + link (via the dev endpoints). */
  user: string;
  /** Ordered conversation turns. */
  turns: ScenarioTurn[];
}
