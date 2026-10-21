import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { printUpSummary } from "../../src/commands/up/handler.js";
import { buildUpSummary } from "../../src/commands/up/summary.js";
import type { UpOutcome } from "../../src/commands/up/summary.types.js";
import { CLIStore } from "../../src/ui/store.js";

const READY: UpOutcome = {
  webUrl: "http://localhost:3000",
  localhostUrl: "http://localhost:3000",
  lanUrls: ["http://192.168.64.7:3000"],
  noStart: false,
  stillStarting: false,
  setupComplete: false,
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

describe("gaia up summary for a domain without its certificate", () => {
  const problem =
    "Let's Encrypt couldn't reach this machine on port 80. Open ports 80 and 443 to the internet in your cloud provider's firewall (security group) or router; Caddy retries on its own.";
  const outcome: UpOutcome = {
    ...READY,
    webUrl: "https://gaia.example.com",
    certificateProblem: problem,
  };

  it("doesn't claim success, and says why HTTPS isn't ready", () => {
    const summary = buildUpSummary(outcome);

    expect(summary.tone).toBe("pending");
    expect(summary.headline).toBe(
      "GAIA is running · its HTTPS certificate isn't ready",
    );
    expect(summary.rows).toContainEqual({
      label: "HTTPS",
      text: `${problem} https://gaia.example.com works once the certificate arrives.`,
      tone: "warn",
    });
  });

  it("sends the browser to the address that works now, not the https one", () => {
    const next = buildUpSummary({
      ...outcome,
      localhostUrl: "http://localhost",
      lanUrls: [],
    }).rows[0];

    expect(next?.label).toBe("Next");
    expect(next?.url).toBe("http://localhost/setup");
  });

  it("prints the reason in plain output too", () => {
    expect(printed(outcome)).toContain("security group");
  });
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

  it("names the unsaved key instead of 'nothing to do' when it was the only thing that failed", () => {
    const summary = buildUpSummary({
      ...READY,
      startedServices: 0,
      unsavedProvider: "openai",
    });

    expect(summary.headline).toBe(
      "GAIA is already running · your OpenAI key wasn't saved",
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

  it("sends the browser to gaia.local once it is set up, with localhost alone as the fallback", () => {
    const summary = buildUpSummary({ ...READY, localUrl: "http://gaia.local" });

    expect(summary.rows).toEqual([
      {
        label: "Next",
        text: "Open http://gaia.local/setup to create your admin account.",
        url: "http://gaia.local/setup",
        tone: "primary",
      },
      { label: "Also at", text: "http://localhost:3000", tone: "dim" },
    ]);
  });

  it("lets a domain win over every other address", () => {
    const next = buildUpSummary({
      ...READY,
      webUrl: "https://gaia.example.com",
    }).rows[0];

    expect(next?.url).toBe("https://gaia.example.com/setup");
  });

  it("keeps the card to the next step and the other addresses", () => {
    const labels = buildUpSummary(READY).rows.map((r) => r.label);

    expect(labels).toEqual(["Next", "Also at"]);
  });

  it("says in one warning line why gaia.local isn't set up, and the run still succeeds", () => {
    const summary = buildUpSummary({
      ...READY,
      localNameProblem: "avahi-daemon isn't running",
    });

    expect(summary.tone).toBe("success");
    expect(summary.rows.filter((r) => r.tone === "warn")).toEqual([
      {
        label: "gaia.local",
        text: "isn't set up: avahi-daemon isn't running",
        tone: "warn",
      },
    ]);
  });

  it("says how to trust a local certificate's authority", () => {
    const row = buildUpSummary({
      ...READY,
      webUrl: "https://gaia.test",
      localCertificate: true,
    }).rows.find((r) => r.label === "Certificate");

    expect(row?.tone).toBe("warn");
    expect(row?.text).toContain(
      "docker cp gaia-selfhost-proxy-1:/data/caddy/pki/authorities/local/root.crt",
    );
  });

  it("prints the same card without a terminal, commands in two columns", () => {
    const out = printed(READY);

    expect(out).toContain("✓ GAIA is running · ready in 3m 12s");
    expect(out).toContain("  Next            Open http://localhost:3000/setup");
    expect(out).toContain("  gaia status   check health");
  });
});
