/**
 * Typed schema for the JSONL transcript the harness emits.
 *
 * Every line of a transcript file is one {@link TranscriptEvent} serialized as
 * compact JSON. Tests (and the scenario runner) assert against this structure,
 * so it is the harness's public contract — keep it stable and additive.
 *
 * Events carry the *emulated* platform and the final, already-rendered payload
 * (run through that platform's real markdown converter), so a transcript is a
 * faithful record of exactly what the platform SDK would have received.
 */

import type { PlatformName } from "@gaia/shared/bots";

/** Fields stamped on every event by the recorder. */
export interface TranscriptEventBase {
  /** Emulated platform this event belongs to (e.g. `"telegram"`). */
  platform: PlatformName;
  /** Monotonic sequence number, starting at 0, incremented per event. */
  seq: number;
  /**
   * Milliseconds elapsed since the recorder was created, from a monotonic
   * clock (`performance.now`), so ordering is stable even if the wall clock
   * jumps.
   */
  t: number;
  /**
   * Wall-clock time of the event (epoch ms). `t` only orders one process's
   * events; this orders them against another sender's, e.g. the reply to a
   * "stop" sent while a run was still delivering.
   */
  at: number;
}

/** The inbound user message that started (or continued) a turn. */
export interface InboundEvent extends TranscriptEventBase {
  type: "inbound";
  /** Platform-native user id the message was injected as. */
  userId: string;
  /** Channel/conversation id (defaults to the user id for DM-style platforms). */
  channelId: string;
  /** Synthetic platform message id, the target a reaction to this message names. */
  messageId: string;
  /** The raw message text as the user "typed" it (pre-conversion). */
  text: string;
}

/** A brand-new message bubble delivered to the channel. */
export interface SendEvent extends TranscriptEventBase {
  type: "send";
  /** Synthetic message id assigned by the harness. */
  messageId: string;
  /** Final rendered text the platform SDK would receive. */
  text: string;
  /** `text.length` — the value the platform's length cap is checked against. */
  length: number;
  /** The platform message this one answers natively, when the reply quotes one. */
  replyTo?: string;
}

/** An in-place edit of a previously-sent bubble. */
export interface EditEvent extends TranscriptEventBase {
  type: "edit";
  messageId: string;
  text: string;
  length: number;
}

/** A delivered bubble taken back off the screen (a retracted reply's later bubbles). */
export interface DeleteEvent extends TranscriptEventBase {
  type: "delete";
  messageId: string;
}

/** Typing / "thinking" indicator lifecycle. */
export interface TypingEvent extends TranscriptEventBase {
  type: "typing";
  state: "start" | "stop";
}

/** An ephemeral (invoker-only) message, e.g. an auth link in a public channel. */
export interface EphemeralEvent extends TranscriptEventBase {
  type: "ephemeral";
  text: string;
}

/** A structured rich message (Discord embed / markdown fallback on others). */
export interface RichEvent extends TranscriptEventBase {
  type: "rich";
  title: string;
  /** Rendered representation of the rich payload for the emulated platform. */
  text: string;
}

/**
 * A backend-originated (proactive) message delivered through the real outbound
 * RabbitMQ consumer — recorded by the adapter's `deliverOutbound`.
 */
export interface OutboundDeliveryEvent extends TranscriptEventBase {
  type: "outbound-delivery";
  /** Platform-native destination id the backend addressed. */
  destinationId: string;
  /** Already-rendered text the consumer handed to the adapter. */
  text: string;
}

/**
 * A backend-originated file/photo delivered through the real outbound consumer —
 * recorded by the adapter's `deliverOutboundFile` after the bytes are fetched.
 */
export interface OutboundAttachmentEvent extends TranscriptEventBase {
  type: "outbound-attachment";
  /** Platform-native destination id the backend addressed. */
  destinationId: string;
  filename: string;
  /** Caption the platform shows beside the file; empty when the envelope carried none. */
  text: string;
  /** Byte length actually fetched — a failed download can't look like a success. */
  bytes: number;
  contentType: string;
}

/** An emoji attached natively to an existing message — a live ack or an outbound reaction. */
export interface ReactionEvent extends TranscriptEventBase {
  type: "reaction";
  /** Platform-native destination (chat/channel/user) the reacted message lives in. */
  destinationId: string;
  /** Platform message id the emoji was attached to. */
  targetMessageId: string;
  emoji: string;
  /** GAIA's earlier reaction on that message, which this one replaces. */
  replaces: string | null;
}

/** Discriminated union of every transcript event. */
export type TranscriptEvent =
  | InboundEvent
  | SendEvent
  | EditEvent
  | DeleteEvent
  | TypingEvent
  | EphemeralEvent
  | RichEvent
  | OutboundDeliveryEvent
  | OutboundAttachmentEvent
  | ReactionEvent;

/** Event payload before the recorder stamps `platform`, `seq`, and `t`. */
export type TranscriptEventInput =
  | Omit<InboundEvent, keyof TranscriptEventBase>
  | Omit<SendEvent, keyof TranscriptEventBase>
  | Omit<EditEvent, keyof TranscriptEventBase>
  | Omit<DeleteEvent, keyof TranscriptEventBase>
  | Omit<TypingEvent, keyof TranscriptEventBase>
  | Omit<EphemeralEvent, keyof TranscriptEventBase>
  | Omit<RichEvent, keyof TranscriptEventBase>
  | Omit<OutboundDeliveryEvent, keyof TranscriptEventBase>
  | Omit<OutboundAttachmentEvent, keyof TranscriptEventBase>
  | Omit<ReactionEvent, keyof TranscriptEventBase>;
