import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";

const install = mkdtempSync(path.join(tmpdir(), "gaia-up-domain-"));
mkdirSync(path.join(install, "infra", "docker"), { recursive: true });
writeFileSync(
  path.join(install, "infra", "docker", ".env"),
  "WEB_HOST_PORT=80\nHTTPS_HOST_PORT=443\nGAIA_DOMAIN=gaia.test\nGAIA_VERSION=v0.7.0\n",
);

const readiness = vi.hoisted(() => ({
  waitForUpReadiness: vi.fn(async () => ({ ready: true })),
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
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  isGaiaInstall: () => true,
  detectSetupMode: async () => "selfhost",
  startServices: async () => ({ startedServices: 0 }),
}));
vi.mock("../../src/lib/prerequisite-install.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/prerequisite-install.js")
  >()),
  ensurePrerequisites: async () => "ready",
}));
vi.mock("../../src/lib/image-availability.js", () => ({
  findReleaseImageGap: async () => null,
}));
vi.mock("../../src/lib/flow-utils.js", () => ({
  runPortChecks: async () => ({}),
}));
vi.mock("../../src/lib/env-setup.js", () => ({
  runEnvSetup: async () => undefined,
}));
vi.mock("../../src/lib/readiness.js", () => readiness);
vi.mock("../../src/lib/setup-endpoints.js", () => ({
  readSetupEndpoint: async () => ({ data: { needs_setup: false } }),
}));

import { runUpFlow } from "../../src/commands/up/flow.js";
import type { UpOutcome } from "../../src/commands/up/summary.types.js";
import { createStore } from "../../src/ui/store.js";

afterAll(() => rmSync(install, { recursive: true, force: true }));

describe("gaia up again on an install with a domain, without --domain", () => {
  it("waits for GAIA where the install serves it, and sends the browser to the domain", async () => {
    const store = createStore();

    await runUpFlow(store, { yes: true });

    expect(store.currentState.error).toBeNull();
    expect(readiness.waitForUpReadiness).toHaveBeenCalledWith(
      store,
      { apiUrl: "http://localhost:80/api/v1", webPort: 80 },
      expect.any(Function),
    );
    const outcome = store.currentState.data.upOutcome as UpOutcome;
    expect(outcome.webUrl).toBe("https://gaia.test");
    expect(outcome.localCertificate).toBe(true);
  });
});
