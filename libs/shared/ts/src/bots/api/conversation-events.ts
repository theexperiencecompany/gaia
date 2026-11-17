/**
 * Reads a conversation's events stream (`GET /conversations/{id}/events`) as
 * typed events. One call is one connection: it ends when the server closes it
 * or goes quiet past the keepalive, and the caller reconnects with the newest
 * stream id it saw.
 *
 * @module
 */
import type { Readable } from "node:stream";
import type { AxiosInstance } from "axios";
import {
  type FrameParseError,
  parseConversationEvent,
} from "../../conversation/frames";
import type { ConversationFrame } from "../../conversation/types";

/** A frame this build's schema cannot read: the server is ahead of the bot, which a reconnect cannot fix. */
export class UnreadableFrameError extends Error {
  constructor(readonly parseError: FrameParseError) {
    super(
      parseError.kind === "invalid_frame"
        ? `unreadable conversation frame: ${parseError.issues.join("; ")}`
        : "unreadable conversation frame: invalid JSON",
    );
    this.name = "UnreadableFrameError";
  }
}

/** The server sends a keepalive every 15 s; three missed means the connection is dead. */
const EVENTS_INACTIVITY_MS = 45_000;

/** Splits SSE text into the `data:` payload of each complete event, keeping the unfinished tail. */
function takeSseData(buffer: string): { data: string[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const data = blocks.flatMap((block) => {
    const lines = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trimStart());
    return lines.length > 0 ? [lines.join("\n")] : [];
  });
  return { data, rest };
}

/** Yields every frame on one connection to the conversation's events stream, opening with its screen. */
export async function* readConversationEvents(
  client: AxiosInstance,
  headers: Record<string, string>,
  conversationId: string,
  signal: AbortSignal,
): AsyncGenerator<ConversationFrame> {
  const response = await client.get(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/events`,
    {
      responseType: "stream",
      signal,
      headers: { Accept: "text/event-stream", ...headers },
    },
  );
  const stream = response.data as Readable;
  let quiet: ReturnType<typeof setTimeout> | null = null;
  const heard = (): void => {
    if (quiet) clearTimeout(quiet);
    quiet = setTimeout(() => stream.destroy(), EVENTS_INACTIVITY_MS);
  };
  heard();
  let buffer = "";
  try {
    for await (const chunk of stream) {
      heard();
      buffer += typeof chunk === "string" ? chunk : chunk.toString("utf8");
      const { data, rest } = takeSseData(buffer.replaceAll("\r\n", "\n"));
      buffer = rest;
      for (const raw of data) {
        const parsed = parseConversationEvent(raw);
        // A frame this build cannot read is never guessed at, nor skipped past: whatever it held would never reach the chat.
        if (!parsed.ok) throw new UnreadableFrameError(parsed.error);
        yield parsed.frame;
      }
    }
  } finally {
    if (quiet) clearTimeout(quiet);
    stream.destroy();
  }
}
