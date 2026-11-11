import { describe, expect, it } from "vitest";
import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { deriveToolCallDisplay } from "./toolCallDisplay";

function entry(overrides: Partial<ToolCallEntry>): ToolCallEntry {
  return {
    tool_name: "call_executor",
    tool_category: "executor",
    message: "Working on it",
    ...overrides,
  };
}

describe("deriveToolCallDisplay", () => {
  it("never shows the raw tool name under a curated label", () => {
    const display = deriveToolCallDisplay(
      entry({
        tool_name: "spawn_subagent",
        message: "Working on part of it",
        show_category: false,
      }),
    );

    expect(display.primaryLabel).toBe("Working on part of it");
    expect(display.hasCategoryText).toBe(false);
    expect(display.secondaryLabel).not.toContain("spawn_subagent");
  });

  it("still names the app a tool belongs to", () => {
    const display = deriveToolCallDisplay(
      entry({
        tool_name: "GMAIL_FETCH_EMAILS",
        tool_category: "gmail",
        message: "Fetch emails",
        integration_name: "Gmail",
      }),
    );

    expect(display.secondaryLabel).toBe("Gmail");
    expect(display.hasCategoryText).toBe(true);
  });
});
