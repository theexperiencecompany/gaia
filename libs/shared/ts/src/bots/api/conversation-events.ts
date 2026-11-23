/**
 * Reads a conversation's events stream (`GET /conversations/{id}/events`) as
 * typed events. One call is one connection: it ends when the server closes it
 * or goes quiet past the keepalive, and the caller reconnects with the newest
 * stream id it saw.
 *
 * @module
 */
import type { Readable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import type { AxiosInstance } from "axios";
import { parseConversationEvent } from "../../conversation/frames";
import type { ConversationFrame } from "../../conversation/types";
import { wideLog } from "../utils/wide-events";

/** The server sends a keepalive every 15 s; three missed means the connection is dead. */
const EVENTS_INACTIVITY_MS = 45_000;

/** The `data:` payload of one SSE event; none for a comment such as the keepalive. */
function eventData(block: string): string[] {
  const lines = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart());
  return lines.length > 0 ? [lines.join("\n")] : [];
}

/**
 * Cuts SSE text, fed chunk by chunk, into the `data:` payload of each complete event.
 *
 * Each chunk is scanned once: an unfinished event's chunks are held apart and joined
 * when its end arrives, so an event of any size costs time in proportion to its length.
 */
function sseDataSplitter(): (text: string) => string[] {
  let held: string[] = [];
  // A line ending the chunk stopped inside: its other half may open the next chunk.
  let carry = "";
  return (text) => {
    let rest = carry + text;
    const endsCr = rest.endsWith("\r");
    if (endsCr) rest = rest.slice(0, -1);
    rest = rest.replaceAll("\r\n", "\n");
    const data: string[] = [];
    let end = rest.indexOf("\n\n");
    while (end !== -1) {
      held.push(rest.slice(0, end));
      data.push(...eventData(held.join("")));
      held = [];
      rest = rest.slice(end + 2);
      end = rest.indexOf("\n\n");
    }
    const endsLf = rest.endsWith("\n");
    held.push(endsLf ? rest.slice(0, -1) : rest);
    carry = `${endsLf ? "\n" : ""}${endsCr ? "\r" : ""}`;
    return data;
  };
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
  // A character's bytes may arrive in two chunks; the decoder holds the first until the second.
  const decoder = new StringDecoder("utf8");
  const split = sseDataSplitter();
  try {
    for await (const chunk of stream) {
      heard();
      for (const raw of split(decoder.write(chunk))) {
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
        yield parsed.frame;
      }
    }
  } finally {
    if (quiet) clearTimeout(quiet);
    stream.destroy();
  }
}
