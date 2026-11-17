/**
 * Where one reply's messages stand on the platform, and the one function that
 * moves them: every send, edit and delete ReplyDelivery runs is reported here,
 * and the cursor the server keeps is read from the result.
 *
 * Pure. Slots are numbered by the delivery machine (bubble-delivery.ts) in the
 * order it opens messages; a reopened slot is a message an earlier follow left
 * mid-bubble, reached at the same number.
 */

import type { MessageSlot } from "../utils/bubble-delivery.types";

/** One message of the reply, by its slot. */
export type SlotState =
  /** Recorded before its send: the platform may hold it, with no id to reach it by. */
  | { readonly status: "sending" }
  /** On the platform, its bubble still being written. */
  | { readonly status: "shown"; readonly id: string }
  /**
   * Left mid-bubble by an earlier follow, which showed an unknown prefix of it: text
   * written to it is held and edited in once its bubble is final, never back to less.
   */
  | {
      readonly status: "reopened";
      readonly id: string;
      readonly held: string | null;
    }
  /** Its bubble is final. */
  | { readonly status: "final"; readonly id: string };

export interface ReplyProgress {
  /** Bubbles of the reply final on the platform, those an earlier follow delivered included. */
  readonly bubbles: number;
  readonly slots: ReadonlyMap<MessageSlot, SlotState>;
}

export type ProgressEvent =
  | { readonly kind: "sending"; readonly slot: MessageSlot }
  | { readonly kind: "sent"; readonly slot: MessageSlot; readonly id: string }
  | { readonly kind: "held"; readonly slot: MessageSlot; readonly text: string }
  | { readonly kind: "discarded"; readonly slot: MessageSlot }
  /** The reply's first `bubbles` bubbles are final: every slot written so far is. */
  | { readonly kind: "delivered"; readonly bubbles: number };

/** What a restarted follow is told: final bubbles, and the open bubble's messages (null: a send never confirmed). */
export interface DeliveryRecord {
  readonly bubbles: number;
  readonly openMessageIds: readonly (string | null)[];
}

/** The progress an earlier follow's record leaves: its open messages reopened, an unconfirmed send dropped. */
export function resumeProgress(record: DeliveryRecord): ReplyProgress {
  const slots = new Map<MessageSlot, SlotState>();
  for (const [slot, id] of record.openMessageIds.entries()) {
    if (id !== null) slots.set(slot, { status: "reopened", id, held: null });
  }
  return { bubbles: record.bubbles, slots };
}

/** Whether this delivery wrote the slot (a reopened one only once text was held for it). */
function written(slot: SlotState): boolean {
  return slot.status !== "reopened" || slot.held !== null;
}

function withSlot(
  progress: ReplyProgress,
  slot: MessageSlot,
  state: SlotState | null,
): ReplyProgress {
  const slots = new Map(progress.slots);
  if (state === null) slots.delete(slot);
  else slots.set(slot, state);
  return { ...progress, slots };
}

/** The one transition: the progress after event. A sent or held slot that is not open is a bug, and throws. */
export function nextProgress(
  progress: ReplyProgress,
  event: ProgressEvent,
): ReplyProgress {
  switch (event.kind) {
    case "sending":
      return withSlot(progress, event.slot, { status: "sending" });
    case "sent":
      if (progress.slots.get(event.slot)?.status !== "sending")
        throw new Error(`slot ${event.slot} was sent without being recorded`);
      return withSlot(progress, event.slot, { status: "shown", id: event.id });
    case "held": {
      const slot = progress.slots.get(event.slot);
      if (slot?.status !== "reopened")
        throw new Error(`slot ${event.slot} is not a reopened message`);
      return withSlot(progress, event.slot, { ...slot, held: event.text });
    }
    case "discarded":
      return withSlot(progress, event.slot, null);
    case "delivered": {
      const slots = new Map<MessageSlot, SlotState>();
      for (const [at, slot] of progress.slots) {
        const final =
          written(slot) && slot.status !== "sending"
            ? ({ status: "final", id: slot.id } as const)
            : slot;
        slots.set(at, final);
      }
      return { bubbles: event.bubbles, slots };
    }
    default: {
      const unhandled: never = event;
      return unhandled;
    }
  }
}

/** The record the server keeps for this progress. */
export function recordOf(progress: ReplyProgress): DeliveryRecord {
  const openMessageIds = [...progress.slots.values()].flatMap((slot) => {
    if (slot.status === "final") return [];
    return [slot.status === "sending" ? null : slot.id];
  });
  return { bubbles: progress.bubbles, openMessageIds };
}

/** Reopened slots this delivery never wrote: messages the finished reply did not reach. */
export function untouchedReopened(
  progress: ReplyProgress,
): [MessageSlot, string][] {
  return [...progress.slots].flatMap(([at, slot]) =>
    slot.status === "reopened" && slot.held === null ? [[at, slot.id]] : [],
  );
}

/** Reopened slots holding their bubble's final text, to edit in once it is final. */
export function heldReopened(progress: ReplyProgress): [MessageSlot, string][] {
  return [...progress.slots].flatMap(([at, slot]) =>
    slot.status === "reopened" && slot.held !== null ? [[at, slot.held]] : [],
  );
}
