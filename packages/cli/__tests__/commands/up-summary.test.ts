import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { printUpSummary } from "../../src/commands/up/handler.js";
import {
  buildUpSummary,
  type UpOutcome,
} from "../../src/commands/up/summary.js";
import { CLIStore } from "../../src/ui/store.js";

const READY: UpOutcome = {
  webUrl: "http://localhost:3000",
  reachableUrls: ["http://localhost:3000", "http://192.168.64.7:3000"],
  noStart: false,
  stillStarting: false,
  setupComplete: false,
  codeSandbox: false,
  joinedDockerGroup: false,
  elapsedMs: 192_000,
  startedServices: 9,
};

/** Everything printUpSummary wrote for a finished run with this outcome. */
function printed(outcome: UpOutcome): string {
  let text = "";
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    text += String(chunk);
    return true;
  });
  const store = new CLIStore();
  store.updateData("upOutcome", outcome);
  printUpSummary(store);
  return text;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("gaia up summary", () => {
  it("leads with one action, the setup page on the address the summary opens", () => {
    const summary = buildUpSummary(READY);

    expect(summary.headline).toBe("GAIA is running · ready in 3m 12s");
    expect(summary.rows[0]).toMatchObject({
      label: "Next",
      url: "http://localhost:3000/setup",
      tone: "primary",
    });
    expect(summary.rows.map((r) => r.text).join("\n")).not.toContain("/api/v1");
  });

  it("lists the other addresses once, as secondary", () => {
    const also = buildUpSummary(READY).rows.find((r) => r.label === "Also at");

    expect(also).toEqual({
      label: "Also at",
      text: "http://192.168.64.7:3000",
      tone: "dim",
    });
  });

  it("opens GAIA itself once setup is complete", () => {
    const next = buildUpSummary({ ...READY, setupComplete: true }).rows[0];

    expect(next?.text).toBe("Open http://localhost:3000");
  });

  it("says a re-run found GAIA already running instead of claiming it started it", () => {
    expect(buildUpSummary({ ...READY, startedServices: 0 }).headline).toBe(
      "GAIA is already running · nothing to do",
    );
  });

  it("says set up, not running, when --no-start started nothing", () => {
    const summary = buildUpSummary({ ...READY, noStart: true });

    expect(summary.headline).toBe("GAIA is set up · nothing was started");
    expect(summary.tone).toBe("pending");
  });

  it("never shouts", () => {
    for (const outcome of [READY, { ...READY, stillStarting: true }]) {
      expect(buildUpSummary(outcome).headline).not.toContain("!");
    }
  });

  it("prints the same card without a terminal, commands in two columns", () => {
    const out = printed(READY);

    expect(out).toContain("✓ GAIA is running · ready in 3m 12s");
    expect(out).toContain("  Next            Open http://localhost:3000/setup");
    expect(out).toContain("  gaia status   check health");
  });
});
