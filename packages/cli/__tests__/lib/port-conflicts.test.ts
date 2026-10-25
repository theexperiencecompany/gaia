import { describe, expect, it } from "vitest";
import { resolvePortConflicts } from "../../src/lib/port-conflicts.js";
import type { PortCheckResult } from "../../src/lib/prerequisites.types.js";

function taken(
  defaultPort: number,
  port: number,
  usedBy?: string,
  alternative?: number,
): PortCheckResult {
  return {
    defaultPort,
    port,
    service: "Web Frontend",
    available: false,
    ...(usedBy ? { usedBy } : {}),
    ...(alternative ? { alternative } : {}),
  };
}

const free = (defaultPort: number, port: number): PortCheckResult => ({
  defaultPort,
  port,
  service: "Web Frontend (HTTPS)",
  available: true,
});

describe("resolvePortConflicts", () => {
  it("refuses a domain's port 80 held by another program, naming it and how to stop it", () => {
    const outcome = resolvePortConflicts(
      [taken(3000, 80, "nginx", 81), free(3443, 443)],
      {
        planned: { 3000: 80, 3443: 443 },
        fixed: { 3000: "domain", 3443: "domain" },
        policy: "move",
      },
    );

    expect("error" in outcome && outcome.error).toMatch(
      /Port 80 is in use by nginx.*domain needs ports 80 and 443/s,
    );
    expect("error" in outcome && outcome.error).toContain(
      "sudo systemctl stop nginx",
    );
    expect("error" in outcome && outcome.error).not.toContain("--web-port");
  });

  it("says how to find an unnamed holder of a domain port", () => {
    const outcome = resolvePortConflicts([taken(3443, 443)], {
      planned: { 3443: 443 },
      fixed: { 3443: "domain" },
      policy: "move",
    });

    expect("error" in outcome && outcome.error).toContain("sudo ss -ltnp");
  });

  it("never moves a --web-port the user chose, and names the next free one", () => {
    const outcome = resolvePortConflicts([taken(3000, 8080, "java", 8081)], {
      planned: { 3000: 8080 },
      fixed: { 3000: "web-port" },
      policy: "move",
    });

    expect("error" in outcome && outcome.error).toContain(
      "gaia up --web-port 8081",
    );
  });

  it("moves a default port with --yes and says where GAIA went", () => {
    const outcome = resolvePortConflicts(
      [taken(3000, 3000, "node", 3001), free(3443, 3443)],
      { planned: {}, fixed: {}, policy: "move" },
    );

    expect(outcome).toEqual({
      overrides: { 3000: 3001 },
      moved: ["Port 3000 was in use by node, so GAIA uses 3001."],
    });
  });

  it("moves a port an earlier run chose, keyed by its default so compose reads it", () => {
    const outcome = resolvePortConflicts([taken(3000, 3001, "node", 3002)], {
      planned: { 3000: 3001 },
      fixed: {},
      policy: "move",
    });

    expect(outcome).toEqual({
      overrides: { 3000: 3002 },
      moved: ["Port 3001 was in use by node, so GAIA uses 3002."],
    });
  });

  it("fails without a terminal or --yes, naming the flag that picks the port", () => {
    const outcome = resolvePortConflicts(
      [taken(3000, 3000, "node", 3001), taken(3443, 3443, undefined, 3444)],
      { planned: {}, fixed: {}, policy: "fail" },
    );

    const error = "error" in outcome ? outcome.error : "";
    expect(error).toContain("gaia up --web-port 3001");
    expect(error).toContain("--yes");
    expect(error).toContain("Port 3443");
  });

  it("keeps the ports already planned when nothing is taken", () => {
    expect(
      resolvePortConflicts([free(3000, 80), free(3443, 443)], {
        planned: { 3000: 80, 3443: 443 },
        fixed: {},
        policy: "fail",
      }),
    ).toEqual({ overrides: { 3000: 80, 3443: 443 }, moved: [] });
  });
});
