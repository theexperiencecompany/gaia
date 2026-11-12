import { describe, expect, it } from "vitest";
import type { ArtifactCardData } from "../artifacts/openuiArtifacts";
import { parseChatStreamEvent } from "./streaming";
import { applyStreamEvent, createTurnAccumulator } from "./turnAccumulator";

const header = { stream_id: "s1", kind: "dashboard", title: "Atlas launch" };

function fold(frames: object[]) {
  return frames
    .flatMap((frame) => parseChatStreamEvent(JSON.stringify(frame)))
    .reduce(applyStreamEvent, createTurnAccumulator());
}

describe("artifact stream frames", () => {
  it("accumulate a program into one streaming card", () => {
    const acc = fold([
      { artifact_delta: { ...header, delta: 'root = Artifact("A", ' } },
      { artifact_delta: { ...header, delta: '"b", [], [])\n' } },
    ]);

    expect(acc.toolData).toHaveLength(1);
    expect(acc.toolData[0].tool_name).toBe("artifact_done");
    expect(acc.toolData[0].data).toMatchObject({
      stream_id: "s1",
      status: "streaming",
      program: 'root = Artifact("A", "b", [], [])\n',
    } satisfies Partial<ArtifactCardData>);
  });

  it("are replaced in place by the persisted artifact_done entry", () => {
    const acc = fold([
      { artifact_delta: { ...header, delta: "root = " } },
      { tool_data: { tool_name: "weather_data", data: {} } },
      {
        tool_data: {
          tool_name: "artifact_done",
          data: { ...header, status: "ready", artifact_id: "a1" },
        },
      },
    ]);

    expect(acc.toolData.map((e) => e.tool_name)).toEqual([
      "artifact_done",
      "weather_data",
    ]);
    expect(acc.toolData[0].data).toEqual({
      ...header,
      status: "ready",
      artifact_id: "a1",
      program: "root = ",
    });
  });

  it("keep two artifacts in one turn apart", () => {
    const acc = fold([
      { artifact_delta: { ...header, delta: "a" } },
      { artifact_delta: { ...header, stream_id: "s2", delta: "b" } },
      { artifact_delta: { ...header, delta: "c" } },
    ]);

    expect(
      acc.toolData.map((e) => (e.data as ArtifactCardData).program),
    ).toEqual(["ac", "b"]);
  });
});
