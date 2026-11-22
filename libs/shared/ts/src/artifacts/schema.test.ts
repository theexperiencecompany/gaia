import { describe, expect, it } from "vitest";
import { ArtifactCardDataSchema } from "./schema";

const header = { stream_id: "s1", kind: "dashboard", title: "Atlas launch" };

describe("an artifact_done card", () => {
  it("reads a ready card with its stored artifact", () => {
    expect(
      ArtifactCardDataSchema.parse({
        ...header,
        status: "ready",
        artifact_id: "a1",
      }),
    ).toEqual({ ...header, status: "ready", artifact_id: "a1" });
  });

  it("of a kind this client does not know fails loudly", () => {
    expect(() =>
      ArtifactCardDataSchema.parse({
        ...header,
        kind: "spreadsheet",
        status: "ready",
      }),
    ).toThrow(/kind/);
  });

  it("reads a streaming card with its draft so far", () => {
    expect(
      ArtifactCardDataSchema.parse({
        ...header,
        status: "streaming",
        program: "root = ",
      }),
    ).toEqual({ ...header, status: "streaming", program: "root = " });
  });

  it("with a status the API never sends fails loudly", () => {
    expect(() =>
      ArtifactCardDataSchema.parse({ ...header, status: "pending" }),
    ).toThrow(/status/);
  });
});
