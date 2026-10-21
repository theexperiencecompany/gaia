import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { TranscriptRecorder } from "../../harness/src/transcript";

function lines(file: string): Record<string, unknown>[] {
  return readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

describe("TranscriptRecorder", () => {
  it("has every event on disk the moment it is recorded", () => {
    // Regression: a sender that threw or died mid-run wrote no transcript at
    // all, and the battery read its run as "no outcome reply".
    const file = path.join(
      mkdtempSync(path.join(tmpdir(), "gaia-sim-")),
      "t.jsonl",
    );
    const recorder = new TranscriptRecorder("telegram", file);

    recorder.record({
      type: "inbound",
      userId: "u",
      channelId: "c",
      text: "hi",
    });
    recorder.record({ type: "typing", state: "start" });

    expect(lines(file).map((event) => event.type)).toEqual([
      "inbound",
      "typing",
    ]);
    expect(lines(file)[1]).toMatchObject({ seq: 1, platform: "telegram" });
  });

  it("starts a run's file empty, never appending to an earlier run", () => {
    const file = path.join(
      mkdtempSync(path.join(tmpdir(), "gaia-sim-")),
      "t.jsonl",
    );
    new TranscriptRecorder("telegram", file).record({
      type: "typing",
      state: "start",
    });

    new TranscriptRecorder("telegram", file);

    expect(readFileSync(file, "utf8")).toBe("");
  });
});
