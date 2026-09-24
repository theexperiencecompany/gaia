/**
 * Recorder + JSONL serializer for harness transcripts.
 *
 * The adapter feeds it {@link TranscriptEventInput}s as the real bot pipeline
 * runs; the recorder stamps a monotonic sequence number, a monotonic
 * timestamp and the wall-clock time on each, keeps them in order, and appends
 * each one to the transcript file the moment it is recorded.
 */

import { appendFileSync, writeFileSync } from "node:fs";
import type { PlatformName } from "@gaia/shared/bots";
import type { TranscriptEvent, TranscriptEventInput } from "./transcript.types";

/**
 * Collects transcript events for a single emulated platform in the order they
 * occur, each written to `path` (JSONL) as it happens: a sender that throws,
 * crashes or is killed mid-run keeps every event it saw. One recorder is
 * created per `gaia-sim` invocation and shared across every turn of a scenario.
 */
export class TranscriptRecorder {
  private readonly events: TranscriptEvent[] = [];
  private seq = 0;
  private readonly startedAt = performance.now();

  constructor(
    private readonly platform: PlatformName,
    private readonly path?: string,
  ) {
    if (path) writeFileSync(path, "", "utf8");
  }

  /** Stamps and appends one event, returning the fully-formed record. */
  record(input: TranscriptEventInput): TranscriptEvent {
    const event = {
      ...input,
      platform: this.platform,
      seq: this.seq,
      t: Math.round((performance.now() - this.startedAt) * 1000) / 1000,
      at: Date.now(),
    } as TranscriptEvent;
    this.seq += 1;
    this.events.push(event);
    if (this.path)
      appendFileSync(this.path, `${JSON.stringify(event)}\n`, "utf8");
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
}
