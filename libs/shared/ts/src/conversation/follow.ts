/**
 * Follows a conversation's events stream for a client that shows it (web, mobile).
 *
 * One connection per conversation while anything holds it open. Each frame goes to
 * the platform's store; every connection opens on the server's screen, so a frame the
 * view cannot apply (an index gap) reopens the stream, and a dropped or ended
 * connection reconnects with backoff.
 */

import {
  FRAME_KIND,
  type FrameParseError,
  parseConversationEvent,
} from "./frames";
import type { ConversationFrame, FrameGap } from "./types";

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 15_000;

/** What a platform gives the follower: its transport, its store, and where to report. */
export interface ConversationFollowPorts {
  /** Read one connection, handing over each data line raw; resolves when the server closes it. */
  subscribe: (
    conversationId: string,
    onData: (raw: string) => void,
    signal: AbortSignal,
  ) => Promise<void>;
  /** The subscribe error for a conversation that does not exist yet. */
  isNotFound: (error: unknown) => boolean;
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
  /** Resolves the current wait early: a send just created the conversation, or the caller closed. */
  wake: (() => void) | null;
}

const backoff = (attempt: number): number =>
  Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);

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
    await ports.subscribe(
      conversationId,
      (raw) => {
        if (gap) return;
        const parsed = parseConversationEvent(raw);
        if (!parsed.ok) {
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
        if (gap) controller.abort();
      },
      controller.signal,
    );
    return { gap, delivered };
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
        if (connection.closed) return;
        if (ports.isNotFound(error)) {
          // Nothing to follow until this device's first send creates it.
          await wait(connection, null);
          continue;
        }
        ports.onDrop(conversationId, error);
      }
      if (connection.closed) return;
      if (gap) {
        ports.onReopen(conversationId, gap);
        continue;
      }
      await wait(connection, backoff(attempt));
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
