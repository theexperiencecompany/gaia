import { describe, expect, it } from "vitest";
import { humanToolTitle } from "./tool-title";

describe("humanToolTitle", () => {
  it("uses the backend's curated label instead of the raw tool name", () => {
    expect(
      humanToolTitle({ tool_name: "call_executor", message: "Working on it" }),
    ).toBe("Working on it");
  });

  it("keeps mobile's own copy where it has one", () => {
    expect(
      humanToolTitle({ tool_name: "web_search", message: "Web search" }),
    ).toBe("Searching the web");
  });

  it("falls back to a readable name when no label came with the call", () => {
    expect(humanToolTitle({ tool_name: "create_todo" })).toBe("Create Todo");
  });
});
