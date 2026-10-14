import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { printUpSummary } from "../../src/commands/up/handler.js";
import { CLIStore } from "../../src/ui/store.js";

/** Everything printUpSummary wrote for a finished run with these data. */
function summaryFor(data: Record<string, unknown>): string {
  const lines: string[] = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => {
    lines.push(line);
  });
  const store = new CLIStore();
  for (const [key, value] of Object.entries({
    finished: true,
    upWebUrl: "http://localhost:3000",
    upApiUrl: "http://localhost:3000/api/v1",
    ...data,
  })) {
    store.updateData(key, value);
  }
  printUpSummary(store);
  return lines.join("\n");
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("gaia up summary", () => {
  it("says configured, not ready, when --no-start started nothing", () => {
    const out = summaryFor({ upNoStart: true });

    expect(out).not.toContain("ready");
    expect(out).toContain("GAIA is configured");
    expect(out).toContain("gaia start");
  });

  it("says ready once the started stack answers", () => {
    expect(summaryFor({ upNoStart: false })).toContain("GAIA is ready!");
  });
});
