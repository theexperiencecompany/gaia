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
import { parseConversationEvent } from "../../conversation/frames";
import type { ConversationStreamEvent } from "../../conversation/types";
import { wideLog } from "../utils/wide-events";

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

/** Yields every event on one connection to the conversation's events stream after `after`. */
export async function* readConversationEvents(
  client: AxiosInstance,
  headers: Record<string, string>,
  conversationId: string,
  after: string,
  signal: AbortSignal,
): AsyncGenerator<ConversationStreamEvent> {
  const response = await client.get(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/events`,
    {
      params: { after },
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
        if (!parsed.ok) {
          // A frame this build cannot read is skipped, never guessed at.
          wideLog.warning("conversation_event_unparsed", {
            kind: parsed.error.kind,
            issues:
              parsed.error.kind === "invalid_frame"
                ? parsed.error.issues.join("; ")
                : undefined,
          });
          continue;
        }
        yield parsed.event;
      }
    }
  } finally {
    if (quiet) clearTimeout(quiet);
    stream.destroy();
  }
}
