/**
 * Follows a conversation's events stream for a client that shows it (web, mobile).
 *
 * One connection per conversation while anything holds it open. Each frame goes to
 * the platform's store. A dropped or ended connection reconnects with backoff from the
 * log head its item frames reached, so the server sends only what changed since. The
 * first connection, and the one after a frame the view could not apply or this build
 * could not read, names no head and opens on the server's whole screen.
 */

import { isRetryableStatus, reconnectDelayMs } from "../retry";
import {
  FRAME_KIND,
  type FrameParseError,
  parseConversationEvent,
} from "./frames";
import type { ConversationFrame, FrameGap } from "./types";

/** What a platform gives the follower: its transport, its store, and where to report. */
export interface ConversationFollowPorts {
  /**
   * Read one connection, handing over each data line raw; resolves when the server closes it.
   * after is the log head the view's items reached on this stream, null to open on the whole screen.
   */
  subscribe: (
    conversationId: string,
    onData: (raw: string) => void,
    signal: AbortSignal,
    after: number | null,
  ) => Promise<void>;
  /** The subscribe error for a conversation that does not exist yet. */
  isNotFound: (error: unknown) => boolean;
  /** The status the server refused the stream with, when it answered one. */
  statusOf: (error: unknown) => number | undefined;
  /** Apply one frame to the store; returns the gap when it could not. */
  apply: (conversationId: string, frame: ConversationFrame) => FrameGap | null;
  /** The conversation's title changed; it belongs to the conversation list, not the view. */
  retitle: (conversationId: string, description: string) => void;
  /** Runs once before the first connection: restore saved state, resend what never landed. */
  prepare: (conversationId: string) => Promise<void>;
  onInvalidFrame: (conversationId: string, error: FrameParseError) => void;
  onReopen: (conversationId: string, gap: FrameGap) => void;
  onDrop: (conversationId: string, error: unknown) => void;
}

export interface ConversationFollower {
  /** Follow a conversation while anything holds it open; the returned release closes it. */
  open: (conversationId: string) => () => void;
  /** Reconnect now instead of after the backoff: a send has just landed in this conversation. */
  wake: (conversationId: string) => void;
}

interface Connection {
  refs: number;
  closed: boolean;
  controller: AbortController | null;
  /** The log head the stream's item frames reached; null when the next connection must open on the whole screen. */
  after: number | null;
  /** Resolves the current wait early: a send just created the conversation, or the caller closed. */
  wake: (() => void) | null;
}

/** The frames whose head says how far the view's items reflect the log. */
const ITEM_FRAMES: ReadonlySet<string> = new Set([
  FRAME_KIND.SCREEN,
  FRAME_KIND.SCREEN_INSERT,
  FRAME_KIND.SCREEN_UPDATE,
  FRAME_KIND.SCREEN_PATCH,
]);

function wait(connection: Connection, ms: number | null): Promise<void> {
  return new Promise((resolve) => {
    const timer = ms === null ? null : setTimeout(done, ms);
    function done() {
      if (timer) clearTimeout(timer);
      connection.wake = null;
      resolve();
    }
    connection.wake = done;
  });
}

export function createConversationFollower(
  ports: ConversationFollowPorts,
): ConversationFollower {
  const connections = new Map<string, Connection>();

  async function readStream(
    conversationId: string,
    connection: Connection,
  ): Promise<{ gap: FrameGap | null; delivered: boolean }> {
    const controller = new AbortController();
    connection.controller = controller;
    let gap: FrameGap | null = null;
    let delivered = false;
    // Whether the view has taken every frame of this connection: only then is its head a place to resume from.
    let whole = true;
    const { after } = connection;
    await ports.subscribe(
      conversationId,
      (raw) => {
        if (gap) return;
        const parsed = parseConversationEvent(raw);
        if (!parsed.ok) {
          whole = false;
          connection.after = null;
          ports.onInvalidFrame(conversationId, parsed.error);
          return;
        }
        delivered = true;
        const { frame } = parsed;
        if (frame.kind === FRAME_KIND.CONVERSATION_UPDATED) {
          ports.retitle(conversationId, frame.description);
          return;
        }
        gap = ports.apply(conversationId, frame);
        if (gap) {
          connection.after = null;
          controller.abort();
        } else if (whole && ITEM_FRAMES.has(frame.kind) && "head" in frame) {
          connection.after = Math.max(connection.after ?? 0, frame.head);
        }
      },
      controller.signal,
      after,
    );
    return { gap, delivered };
  }

  /** What a failed connection leads to: stop, reconnect at once (a send woke it), or back off first. */
  async function afterFailure(
    conversationId: string,
    connection: Connection,
    error: unknown,
  ): Promise<"stop" | "reconnect" | "backoff"> {
    if (connection.closed) return "stop";
    if (ports.isNotFound(error)) {
      // Nothing to follow until this device's first send creates it.
      await wait(connection, null);
      return "reconnect";
    }
    ports.onDrop(conversationId, error);
    const status = ports.statusOf(error);
    // A refusal (signed out, forbidden) fails the same way on every reconnect.
    return status !== undefined && !isRetryableStatus(status)
      ? "stop"
      : "backoff";
  }

  async function follow(
    conversationId: string,
    connection: Connection,
  ): Promise<void> {
    await ports.prepare(conversationId);
    let attempt = 0;
    let gap: FrameGap | null = null;
    while (!connection.closed) {
      gap = null;
      try {
        const ended = await readStream(conversationId, connection);
        gap = ended.gap;
        if (ended.delivered) attempt = 0;
      } catch (error) {
        const next = await afterFailure(conversationId, connection, error);
        if (next === "stop") return;
        if (next === "reconnect") continue;
      }
      if (connection.closed) return;
      if (gap) {
        ports.onReopen(conversationId, gap);
        continue;
      }
      await wait(connection, reconnectDelayMs(attempt));
      attempt += 1;
    }
  }

  const open = (conversationId: string): (() => void) => {
    let connection = connections.get(conversationId);
    if (!connection) {
      const opened: Connection = {
        refs: 0,
        closed: false,
        controller: null,
        after: null,
        wake: null,
      };
      connections.set(conversationId, opened);
      connection = opened;
      follow(conversationId, opened).catch((error: unknown) => {
        ports.onDrop(conversationId, error);
      });
    }
    connection.refs += 1;
    const held = connection;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      held.refs -= 1;
      if (held.refs > 0) return;
      held.closed = true;
      held.controller?.abort();
      held.wake?.();
      connections.delete(conversationId);
    };
  };

  const wake = (conversationId: string): void => {
    connections.get(conversationId)?.wake?.();
  };

  return { open, wake };
}
