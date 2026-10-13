import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  spawn,
  readConfig,
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
} = vi.hoisted(() => ({
  spawn: vi.fn(),
  readConfig: vi.fn(),
  assertEngineSupportsCodeSandbox: vi.fn(),
  dockerVolumeExists: vi.fn(),
}));
vi.mock("child_process", () => ({ spawn }));
vi.mock("../../src/lib/config.js", () => ({
  readConfig,
  updateConfig: vi.fn(),
}));
vi.mock("../../src/lib/docker.js", () => ({
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
}));

import { startServices } from "../../src/lib/service-starter.js";

/** A child process that exits 0 on the next tick. */
function exitingProcess(): EventEmitter {
  const proc = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  setImmediate(() => proc.emit("close", 0));
  return proc;
}

/** The compose files a self-host start passed, in order. */
async function composeFilesForStart(
  options?: Parameters<typeof startServices>[5],
): Promise<string[]> {
  await startServices(
    "/no/such/repo",
    "selfhost",
    undefined,
    undefined,
    undefined,
    options,
  );
  const args = spawn.mock.calls[0]?.[1] as string[];
  return args.flatMap((arg, i) => (args[i - 1] === "-f" ? [arg] : []));
}

function resetMocks(): void {
  spawn.mockReset();
  spawn.mockImplementation(exitingProcess);
  readConfig.mockReset();
  assertEngineSupportsCodeSandbox.mockReset();
  dockerVolumeExists.mockReset();
  dockerVolumeExists.mockResolvedValue(false);
}

describe("startServices compose files", () => {
  beforeEach(resetMocks);

  it("never mounts the Docker socket unless the sandbox was opted into", async () => {
    readConfig.mockReturnValue({ repoPath: "/no/such/repo" });

    expect(await composeFilesForStart()).toEqual([
      "docker-compose.selfhost.yml",
    ]);
  });

  it("keeps the saved sandbox opt-in on every later start", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });

    expect(await composeFilesForStart({ pull: "always" })).toEqual([
      "docker-compose.selfhost.yml",
      "docker-compose.sandbox.yml",
    ]);
  });

  it("layers the sandbox on a source build", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });

    expect(await composeFilesForStart({ build: true })).toEqual([
      "docker-compose.selfhost.yml",
      "docker-compose.build.yml",
      "docker-compose.sandbox.yml",
    ]);
  });
});

describe("startServices code-sandbox isolation", () => {
  beforeEach(resetMocks);

  const start = () =>
    startServices("/no/such/repo", "selfhost", undefined, undefined, undefined);

  it("refuses to start the sandbox on an engine that cannot isolate users", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });
    assertEngineSupportsCodeSandbox.mockRejectedValue(
      new Error("needs Docker Engine 26"),
    );

    await expect(start()).rejects.toThrow("Docker Engine 26");
    expect(spawn).not.toHaveBeenCalled();
  });

  it("never checks the engine when the sandbox is off", async () => {
    readConfig.mockReturnValue({});

    await start();

    expect(assertEngineSupportsCodeSandbox).not.toHaveBeenCalled();
  });

  it("migrates the shared sandbox volume read-only after the stack is up", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });
    dockerVolumeExists.mockResolvedValue(true);

    await start();

    expect(dockerVolumeExists).toHaveBeenCalledWith("gaia-sandbox-workspace");
    const migrate = spawn.mock.calls[1]?.[1] as string[];
    expect(migrate).toEqual(
      expect.arrayContaining([
        "run",
        "--rm",
        "--no-deps",
        "gaia-sandbox-workspace:/legacy-sandbox-workspace:ro",
        "gaia-backend",
        "app.scripts.migrate_legacy_sandbox_workspace",
      ]),
    );
    expect(migrate.indexOf("up")).toBe(-1);
    expect(spawn.mock.calls[0]?.[1]).toContain("up");
  });

  it("runs no migration once the shared volume is gone", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });

    await start();

    expect(spawn).toHaveBeenCalledTimes(1);
  });
});
