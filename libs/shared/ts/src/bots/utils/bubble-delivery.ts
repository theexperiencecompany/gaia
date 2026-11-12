/**
 * The state machine that turns one bot reply into platform messages.
 *
 * Pure: each event in, the next state and the ordered sends, edits, deletes and
 * pauses out. The conversation follower's ReplyDelivery runs the operations
 * against the platform.
 *
 * Live platforms (Telegram, Slack) show each bubble as its own message from its
 * first word: the preview only ever holds the bubble being written, a break
 * seals it as it stands, and the next bubble opens a new message. Nothing
 * collapses at the end. A retraction (a hand-off preamble, a retried model
 * attempt) deletes the retracted message's later bubbles and leaves its first
 * one to be overwritten in place by whatever comes next.
 *
 * Other platforms show nothing until a message is final: each kept message is
 * sent when its boundary arrives, bubble by bubble, a pause between them.
 */

import { splitStreamingBubbles } from "../../utils/messageBubbles";
import type {
  Carry,
  DeliveryConfig,
  DeliveryEvent,
  DeliveryOp,
  DeliveryState,
  MessageSlot,
  TurnFields,
} from "./bubble-delivery.types";
import { chunkResponse, PLATFORM_LIMITS, splitOverflow } from "./text";

/** The reply's first message: not on screen yet, so its first text opens it. */
const FIRST_SLOT: MessageSlot = 0;

/**
 * Past this share of the platform limit a live preview holds still, so that when
 * the bubble overflows it can be cut at a sentence between what is shown and the
 * limit instead of taking shown text back.
 */
export const LIVE_PREVIEW_SHARE = 0.9;

const FRESH_CARRY: Carry = { carried: "", from: 0 };

export function initialDeliveryState(): DeliveryState {
  return {
    phase: "idle",
    pending: "",
    sealedBubbles: 0,
    carry: FRESH_CARRY,
    reusable: { slot: FIRST_SLOT },
    nextSlot: FIRST_SLOT + 1,
  };
}

/** One step's working copy: the union flattened so each helper can move it between phases. */
interface Draft extends TurnFields {
  earlier: MessageSlot[];
  live: { slot: MessageSlot; shown: string } | null;
  ops: DeliveryOp[];
  /** A bubble went out earlier in this step, so the next one waits a beat. */
  bubbleSent: boolean;
}

function toDraft(state: DeliveryState): Draft {
  return {
    pending: state.pending,
    sealedBubbles: state.sealedBubbles,
    carry: state.carry,
    reusable: state.reusable,
    nextSlot: state.nextSlot,
    earlier: state.phase === "idle" ? [] : [...state.earlier],
    live: state.phase === "streaming" ? state.live : null,
    ops: [],
    bubbleSent: false,
  };
}

function fromDraft(draft: Draft): DeliveryState {
  const fields: TurnFields = {
    pending: draft.pending,
    sealedBubbles: draft.sealedBubbles,
    carry: draft.carry,
    reusable: draft.reusable,
    nextSlot: draft.nextSlot,
  };
  if (draft.live) {
    return {
      phase: "streaming",
      earlier: draft.earlier,
      live: draft.live,
      ...fields,
    };
  }
  const [first, ...rest] = draft.earlier;
  if (first === undefined) return { phase: "idle", ...fields };
  return { phase: "sealed", earlier: [first, ...rest], ...fields };
}

/** Puts text in a message of its own: the reusable one if there is one, else a new one. */
function openMessage(
  draft: Draft,
  text: string,
  newBubble: boolean,
): MessageSlot {
  if (newBubble && draft.bubbleSent) draft.ops.push({ kind: "pause" });
  if (draft.reusable) {
    const { slot } = draft.reusable;
    draft.reusable = null;
    draft.ops.push({ kind: "edit", slot, text });
    return slot;
  }
  const slot = draft.nextSlot;
  draft.nextSlot += 1;
  draft.ops.push({ kind: "send", slot, text });
  return slot;
}

function fits(text: string, config: DeliveryConfig): boolean {
  return config.render(text).length <= PLATFORM_LIMITS[config.platform];
}

/** The messages a finished bubble becomes, the first never shorter than what is shown of it. */
function finalChunks(
  text: string,
  shownLength: number,
  config: DeliveryConfig,
): string[] {
  if (fits(text, config)) return [text];
  if (shownLength === 0)
    return chunkResponse(text, config.platform, config.render);
  const [first, rest] = splitOverflow(
    text,
    config.platform,
    config.render,
    shownLength,
  );
  return [first, ...chunkResponse(rest, config.platform, config.render)];
}

/** The open bubble's text that no earlier message has taken yet. */
function untaken(draft: Draft, bubble: string): string {
  return (draft.carry.carried + bubble.slice(draft.carry.from)).trimStart();
}

/** Delivers a bubble's final text: into its live preview if it has one, else as new messages. */
function sealBubble(draft: Draft, text: string, config: DeliveryConfig): void {
  const { live } = draft;
  const opsBefore = draft.ops.length;
  draft.live = null;
  draft.carry = FRESH_CARRY;
  if (!text) return;
  const [first, ...rest] = finalChunks(text, live?.shown.length ?? 0, config);
  if (first === undefined) return;
  if (live) {
    if (first !== live.shown) {
      draft.ops.push({ kind: "edit", slot: live.slot, text: first });
    }
    draft.earlier.push(live.slot);
  } else {
    draft.earlier.push(openMessage(draft, first, true));
  }
  for (const chunk of rest) {
    draft.earlier.push(openMessage(draft, chunk, false));
  }
  draft.bubbleSent ||= draft.ops.length > opsBefore;
}

/** Seals every bubble a break has closed since the last step. */
function sealCompleteBubbles(draft: Draft, config: DeliveryConfig): void {
  const { complete } = splitStreamingBubbles(draft.pending);
  for (const bubble of complete.slice(draft.sealedBubbles)) {
    sealBubble(draft, untaken(draft, bubble), config);
  }
  draft.sealedBubbles = complete.length;
}

/** Shows the bubble being written, cutting a full message off it whenever it outgrows one. */
function previewOpenBubble(draft: Draft, config: DeliveryConfig): void {
  const { open } = splitStreamingBubbles(draft.pending);
  if (!open) return;
  let text = untaken(draft, open);
  while (text) {
    const { live } = draft;
    if (live && text === live.shown) return;
    if (fits(text, config)) {
      const limit = PLATFORM_LIMITS[config.platform];
      if (!live) {
        draft.live = { slot: openMessage(draft, text, false), shown: text };
      } else if (config.render(text).length <= limit * LIVE_PREVIEW_SHARE) {
        draft.ops.push({ kind: "edit", slot: live.slot, text });
        draft.live = { slot: live.slot, shown: text };
      }
      return;
    }
    const [chunk, rest] = splitOverflow(
      text,
      config.platform,
      config.render,
      live?.shown.length ?? 0,
    );
    if (live) {
      draft.ops.push({ kind: "edit", slot: live.slot, text: chunk });
      draft.earlier.push(live.slot);
    } else {
      draft.earlier.push(openMessage(draft, chunk, false));
    }
    draft.live = null;
    draft.carry = { carried: rest, from: open.length };
    text = rest;
  }
}

/** The in-flight message is done with: what follows belongs to the next one. */
function closeMessage(draft: Draft): void {
  draft.pending = "";
  draft.sealedBubbles = 0;
  draft.carry = FRESH_CARRY;
  draft.earlier = [];
  draft.live = null;
}

/** Delivers whatever of the in-flight message is not on screen yet, as final bubbles. */
function keepMessage(draft: Draft, config: DeliveryConfig): void {
  sealCompleteBubbles(draft, config);
  const { open } = splitStreamingBubbles(draft.pending);
  if (open) sealBubble(draft, untaken(draft, open), config);
  closeMessage(draft);
}

/** Takes the in-flight message back: its later messages deleted, its first left to overwrite. */
function retractMessage(draft: Draft): void {
  const shown = [...draft.earlier, ...(draft.live ? [draft.live.slot] : [])];
  const [first, ...rest] = shown;
  if (first !== undefined) {
    for (const slot of rest) draft.ops.push({ kind: "delete", slot });
    draft.reusable = { slot: first };
  }
  closeMessage(draft);
}

/** Applies one stream event: the next state, and the platform operations to run, in order. */
export function stepDelivery(
  state: DeliveryState,
  event: DeliveryEvent,
  config: DeliveryConfig,
): { state: DeliveryState; ops: DeliveryOp[] } {
  const draft = toDraft(state);
  switch (event.kind) {
    case "text":
      draft.pending += event.chunk;
      if (config.live) sealCompleteBubbles(draft, config);
      break;
    case "tick":
      if (config.live) previewOpenBubble(draft, config);
      break;
    case "boundary":
      if (event.discarded) retractMessage(draft);
      else keepMessage(draft, config);
      break;
    case "end":
      keepMessage(draft, config);
      break;
    default: {
      const unhandled: never = event;
      return unhandled;
    }
  }
  return { state: fromDraft(draft), ops: draft.ops };
}
