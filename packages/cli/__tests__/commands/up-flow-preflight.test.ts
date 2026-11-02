import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

const install = mkdtempSync(path.join(tmpdir(), "gaia-up-preflight-"));
mkdirSync(path.join(install, "packages", "cli", "selfhost"), {
  recursive: true,
});
writeFileSync(
  path.join(install, "packages", "cli", "selfhost", ".env"),
  "GAIA_VERSION=v0.7.0\n",
);

const GIB = 1024 ** 3;
const fakes = vi.hoisted(() => ({
  checkModePorts: vi.fn(),
  readDockerMemoryBytes: vi.fn(),
  readDockerDiskFree: vi.fn(),
  checkDomainDns: vi.fn(),
  waitForCertificate: vi.fn(),
  startServices: vi.fn(async () => ({ startedServices: 9 })),
}));

vi.mock("../../src/lib/version.js", () => ({
  CLI_VERSION: "0.0.1-test",
  GAIA_RELEASE_IMAGE_TAG: "v0.7.0",
}));
vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/config.js")>()),
  readConfig: () => null,
  updateConfig: () => undefined,
}));
vi.mock("../../src/lib/answers.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/answers.js")>()),
  resolveRecordedInstall: () => install,
}));
vi.mock("../../src/lib/install-root.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/install-root.js")>()),
  isGaiaInstall: () => true,
  isSelfhostOrUnconfigured: async () => true,
  detectSetupMode: async () => "selfhost",
}));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  startServices: fakes.startServices,
}));
vi.mock("../../src/lib/prerequisite-install.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/prerequisite-install.js")
  >()),
  ensurePrerequisites: async () => "ready",
}));
vi.mock("../../src/lib/prerequisites.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/prerequisites.js")>()),
  checkModePorts: fakes.checkModePorts,
}));
vi.mock("../../src/lib/host-resources.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/host-resources.js")>()),
  getDockerRootDir: async () => "/var/lib/docker",
  readDockerDiskFree: fakes.readDockerDiskFree,
  readDockerMemoryBytes: fakes.readDockerMemoryBytes,
}));
vi.mock("../../src/lib/domain-reachability.js", () => ({
  checkDomainDns: fakes.checkDomainDns,
  waitForCertificate: fakes.waitForCertificate,
}));
vi.mock("../../src/lib/image-availability.js", () => ({
  findReleaseImageGap: async () => null,
}));
// Settings are saved as the real setup saves the ports: into the compose env file.
vi.mock("../../src/lib/env-setup.js", async () => {
  const { writeDockerComposeEnv } = await import("../../src/lib/env-writer.js");
  return {
    runEnvSetup: async (
      _store: unknown,
      repoPath: string,
      mode: "selfhost",
      portOverrides: Record<number, number>,
    ) => writeDockerComposeEnv(repoPath, portOverrides, mode),
  };
});
vi.mock("../../src/lib/readiness.js", () => ({
  waitForUpReadiness: async () => ({ ready: true }),
}));
vi.mock("../../src/lib/setup-endpoints.js", () => ({
  readSetupEndpoint: async () => ({ data: { needs_setup: true } }),
}));
vi.mock("../../src/lib/local-name.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/local-name.js")>()),
  setUpLocalName: async () => undefined,
}));

import { runUpFlow } from "../../src/commands/up/flow.js";
import type { UpOutcome } from "../../src/commands/up/summary.types.js";
import type { RunStep } from "../../src/lib/run-steps.js";
import { createStore } from "../../src/ui/store.js";

afterAll(() => rmSync(install, { recursive: true, force: true }));

const DOMAIN_PORT_NOTE =
  "A domain is served on ports 80 and 443, so GAIA moves from port 3000 to 80 and 443.";

function freePorts(_mode: string, planned: Record<number, number>) {
  return [3000, 3443].map((defaultPort) => ({
    defaultPort,
    port: planned[defaultPort] ?? defaultPort,
    service: "Web",
    available: true,
  }));
}

function preflight(store: ReturnType<typeof createStore>): RunStep | undefined {
  return (store.currentState.data.steps as RunStep[]).find(
    (step) => step.id === "preflight",
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  writeFileSync(
    path.join(install, "packages", "cli", "selfhost", ".env"),
    "GAIA_VERSION=v0.7.0\n",
  );
  fakes.checkModePorts.mockImplementation(async (mode, planned) =>
    freePorts(mode, planned),
  );
  fakes.readDockerMemoryBytes.mockResolvedValue(16 * GIB);
  fakes.readDockerDiskFree.mockResolvedValue(100 * GIB);
  fakes.checkDomainDns.mockResolvedValue(null);
  fakes.waitForCertificate.mockResolvedValue(null);
});

describe("gaia up --domain checks the ports it will bind", () => {
  it("checks 80 and 443, and stops on a taken port 80 naming who holds it", async () => {
    fakes.checkModePorts.mockImplementation(async (_mode, planned) => [
      {
        defaultPort: 3000,
        port: planned[3000],
        service: "Web",
        available: false,
        usedBy: "nginx",
        alternative: 81,
      },
      {
        defaultPort: 3443,
        port: planned[3443],
        service: "Web",
        available: true,
      },
    ]);
    const store = createStore();

    await runUpFlow(store, { yes: true, domain: "gaia.example.com" });

    expect(fakes.checkModePorts).toHaveBeenCalledWith(
      "selfhost",
      expect.objectContaining({ 3000: 80, 3443: 443 }),
    );
    expect(store.currentState.error?.message).toMatch(
      /Port 80 is in use by nginx.*sudo systemctl stop nginx/s,
    );
    expect(fakes.startServices).not.toHaveBeenCalled();
  });

  it("warns before starting when the domain's DNS points elsewhere, then goes on", async () => {
    fakes.checkDomainDns.mockResolvedValue(
      "gaia.example.com points to 198.51.100.9, not this machine.",
    );
    const store = createStore();

    await runUpFlow(store, { yes: true, domain: "gaia.example.com" });

    expect(preflight(store)?.warnings).toEqual([
      DOMAIN_PORT_NOTE,
      "gaia.example.com points to 198.51.100.9, not this machine.",
    ]);
    expect(fakes.startServices).toHaveBeenCalled();
  });

  it("says once that the domain moves GAIA off port 3000, and not on a rerun already on 80", async () => {
    const first = createStore();
    await runUpFlow(first, { yes: true, domain: "gaia.example.com" });
    expect(preflight(first)?.warnings).toEqual([DOMAIN_PORT_NOTE]);

    const rerun = createStore();
    await runUpFlow(rerun, { yes: true, domain: "gaia.example.com" });
    expect(preflight(rerun)?.warnings ?? []).toEqual([]);
  });

  it("puts the certificate's problem on the card instead of claiming success", async () => {
    fakes.waitForCertificate.mockResolvedValue(
      "Let's Encrypt couldn't reach this machine on port 80.",
    );
    const store = createStore();

    await runUpFlow(store, { yes: true, domain: "gaia.example.com" });

    const outcome = store.currentState.data.upOutcome as UpOutcome;
    expect(fakes.waitForCertificate).toHaveBeenCalledWith(
      "gaia.example.com",
      443,
    );
    expect(outcome.certificateProblem).toContain("port 80");
  });
});

describe("gaia up checks the machine can hold GAIA", () => {
  it("stops before downloading anything when Docker has too little memory", async () => {
    fakes.readDockerMemoryBytes.mockResolvedValue(4 * GIB);
    const store = createStore();

    await runUpFlow(store, { yes: true });

    expect(store.currentState.error?.message).toMatch(
      /4\.0 GB in total for Docker; GAIA needs at least 6\.0 GB/,
    );
    expect(preflight(store)?.state).toBe("failed");
    expect(fakes.startServices).not.toHaveBeenCalled();
  });

  it("warns, and carries on, when memory is tight", async () => {
    fakes.readDockerMemoryBytes.mockResolvedValue(6.5 * GIB);
    const store = createStore();

    await runUpFlow(store, { yes: true });

    expect(store.currentState.error).toBeNull();
    expect(preflight(store)?.warnings?.[0]).toMatch(
      /6\.5 GB in total for Docker/,
    );
  });

  it("says where a taken port moved with --yes", async () => {
    fakes.checkModePorts.mockImplementation(async () => [
      {
        defaultPort: 3000,
        port: 3000,
        service: "Web",
        available: false,
        usedBy: "node",
        alternative: 3001,
      },
      { defaultPort: 3443, port: 3443, service: "Web", available: true },
    ]);
    const store = createStore();

    await runUpFlow(store, { yes: true });

    expect(preflight(store)?.warnings).toContain(
      "Port 3000 was in use by node, so GAIA uses 3001.",
    );
  });
});
