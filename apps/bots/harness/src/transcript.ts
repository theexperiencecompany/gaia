/**
 * In-memory recorder + JSONL serializer for harness transcripts.
 *
 * The adapter feeds it {@link TranscriptEventInput}s as the real bot pipeline
 * runs; the recorder stamps a monotonic sequence number and a monotonic
 * timestamp on each, keeps them in order, and can serialize the whole run to
 * newline-delimited JSON for on-disk assertion.
 */

import { writeFile } from "node:fs/promises";
import type { PlatformName } from "@gaia/shared/bots";
import type { TranscriptEvent, TranscriptEventInput } from "./transcript.types";

/**
 * Collects transcript events for a single emulated platform in the order they
 * occur, then writes them as JSONL. One recorder is created per `gaia-sim`
 * invocation and shared across every turn of a scenario.
 */
export class TranscriptRecorder {
  private readonly events: TranscriptEvent[] = [];
  private seq = 0;
  private readonly startedAt = performance.now();

  constructor(private readonly platform: PlatformName) {}

  /** Stamps and appends one event, returning the fully-formed record. */
  record(input: TranscriptEventInput): TranscriptEvent {
    const event = {
      ...input,
      platform: this.platform,
      seq: this.seq,
      t: Math.round((performance.now() - this.startedAt) * 1000) / 1000,
    } as TranscriptEvent;
    this.seq += 1;
    this.events.push(event);
    return event;
  }

  /** All recorded events, in order. */
  getEvents(): readonly TranscriptEvent[] {
    return this.events;
  }

  /** Serializes the transcript to newline-delimited JSON (one event per line). */
  toJsonl(): string {
    return this.events.map((event) => JSON.stringify(event)).join("\n");
  }

  /** Writes the transcript as JSONL to `path` (trailing newline included). */
  async writeTo(path: string): Promise<void> {
    const body = this.events.length > 0 ? `${this.toJsonl()}\n` : "";
    await writeFile(path, body, "utf8");
  }
}
