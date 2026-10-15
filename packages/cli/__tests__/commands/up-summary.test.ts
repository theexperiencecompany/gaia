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
    upReachableUrls: ["http://localhost:3000"],
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

  it("lists every address the instance answers at", () => {
    const out = summaryFor({
      upNoStart: false,
      upReachableUrls: ["http://localhost:3000", "http://192.168.64.7:3000"],
    });

    expect(out).toContain("http://192.168.64.7:3000");
  });

  it("says ready once the started stack answers", () => {
    expect(summaryFor({ upNoStart: false })).toContain("GAIA is ready!");
  });

  it("points at the browser wizard while setup is still owed", () => {
    const out = summaryFor({ upNoStart: false, upSetupComplete: false });

    expect(out).toContain(
      "Finish setup in your browser: http://localhost:3000/setup",
    );
  });

  it("only says where to open GAIA once setup is complete", () => {
    const out = summaryFor({ upNoStart: false, upSetupComplete: true });

    expect(out).toContain("Open GAIA at:");
    expect(out).not.toContain("/setup");
  });
});
