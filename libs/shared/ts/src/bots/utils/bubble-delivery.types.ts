/** Types of the bot delivery state machine (bubble-delivery.ts). */

import type { PlatformName } from "../types";

/** A message on screen, numbered in the order this turn opened it. */
export type MessageSlot = number;
export type DeliveryOp =
  | { kind: "edit"; slot: MessageSlot; text: string }
  | { kind: "send"; slot: MessageSlot; text: string }
  | { kind: "delete"; slot: MessageSlot }
  | { kind: "pause" }
  /** The reply's first `bubbles` bubbles are final on screen, once the ops before this one ran. */
  | { kind: "delivered"; bubbles: number };

export type DeliveryEvent =
  /** The reply's bubbles as the server now has them: the last may still grow. */
  | { kind: "bubbles"; bubbles: readonly string[] }
  | { kind: "tick" }
  /** Take back everything shown, its first message left to overwrite. */
  | { kind: "retract" }
  | { kind: "end" };

export interface DeliveryConfig {
  live: boolean;
  platform: PlatformName;
  /** The platform's markdown converter: limits are measured on what it produces. */
  render: (text: string) => string;
}

/** A message whose text the next output may overwrite: the unopened first one, or retracted text. */
export interface Reusable {
  slot: MessageSlot;
}

/** The bubble being written, as `carried + open.slice(from)`: earlier messages took the rest. */
export interface Carry {
  carried: string;
  from: number;
}

export interface TurnFields {
  /** The reply's bubbles so far, as the server split them. */
  pending: readonly string[];
  /** How many of its complete bubbles are delivered. */
  sealedBubbles: number;
  carry: Carry;
  reusable: Reusable | null;
  nextSlot: MessageSlot;
}

/** The in-flight message's bubbles on screen: `earlier` are final, `live` is still growing. */
export type DeliveryState =
  | ({ phase: "idle" } & TurnFields)
  | ({
      phase: "streaming";
      earlier: MessageSlot[];
      live: { slot: MessageSlot; shown: string };
    } & TurnFields)
  | ({
      phase: "sealed";
      earlier: [MessageSlot, ...MessageSlot[]];
    } & TurnFields);
