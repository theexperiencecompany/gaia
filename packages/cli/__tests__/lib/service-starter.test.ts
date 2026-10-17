import { EventEmitter } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  spawn,
  readConfig,
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
  runCompose,
  getDockerAccess,
} = vi.hoisted(() => ({
  spawn: vi.fn(),
  readConfig: vi.fn(),
  assertEngineSupportsCodeSandbox: vi.fn(),
  dockerVolumeExists: vi.fn(),
  runCompose: vi.fn(),
  getDockerAccess: vi.fn(),
}));
vi.mock("child_process", () => ({ spawn }));
vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readConfig,
  updateConfig: vi.fn(),
}));
vi.mock("../../src/lib/docker.js", () => ({
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
}));
vi.mock("../../src/lib/compose-run.js", () => ({ runCompose }));
vi.mock("../../src/lib/docker-access.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  getDockerAccess,
}));
const { writeBotsEnv } = vi.hoisted(() => ({ writeBotsEnv: vi.fn() }));
vi.mock("../../src/lib/bots.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/bots.js")>()),
  writeBotsEnv,
}));

import {
  pullSelfhostImages,
  startServices,
  stopServices,
} from "../../src/lib/service-starter.js";

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

/** The -f files in a docker/compose argument list. */
function filesIn(args: readonly string[] | undefined): string[] {
  return (args ?? []).flatMap((arg, i) =>
    args?.[i - 1] === "-f" ? [arg] : [],
  );
}

/** The arguments of the Nth runCompose call. */
function composeArgs(call = 0): string[] {
  return runCompose.mock.calls[call]?.[0] as string[];
}

function startSelfhost(
  options?: Parameters<typeof startServices>[5],
): Promise<unknown> {
  return startServices(
    "/no/such/repo",
    "selfhost",
    undefined,
    undefined,
    undefined,
    options,
  );
}

/** The compose files a self-host start passed, in order. */
async function composeFilesForStart(
  options?: Parameters<typeof startServices>[5],
): Promise<string[]> {
  await startSelfhost(options);
  return filesIn(composeArgs());
}

function resetMocks(): void {
  spawn.mockReset();
  spawn.mockImplementation(exitingProcess);
  runCompose.mockReset();
  runCompose.mockResolvedValue(undefined);
  getDockerAccess.mockReset();
  getDockerAccess.mockResolvedValue("ready");
  readConfig.mockReset();
  writeBotsEnv.mockReset();
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

describe("self-host chat bots", () => {
  beforeEach(resetMocks);

  it("layers each saved bot's override on every start", async () => {
    readConfig.mockReturnValue({ bots: ["telegram", "slack"] });

    expect(await composeFilesForStart()).toEqual([
      "docker-compose.selfhost.yml",
      "docker-compose.bot-telegram.yml",
      "docker-compose.bot-slack.yml",
    ]);
  });

  it("re-copies the bots' env before compose reads it", async () => {
    readConfig.mockReturnValue({ bots: ["discord"] });

    await composeFilesForStart();

    expect(writeBotsEnv).toHaveBeenCalledWith("/no/such/repo");
    expect(writeBotsEnv.mock.invocationCallOrder[0]).toBeLessThan(
      runCompose.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("touches no bot env when no bot is enabled", async () => {
    readConfig.mockReturnValue({});

    await composeFilesForStart();

    expect(writeBotsEnv).not.toHaveBeenCalled();
  });

  it("pulls the enabled bots' images with the app images on update", async () => {
    readConfig.mockReturnValue({ bots: ["telegram"] });

    await pullSelfhostImages("/no/such/repo", "v1.2.3");

    expect(filesIn(composeArgs())).toContain("docker-compose.bot-telegram.yml");
    expect(composeArgs()).toEqual(
      expect.arrayContaining(["pull", "gaia-backend", "bot-telegram"]),
    );
    expect(runCompose.mock.calls[0]?.[1]).toMatchObject({
      env: { GAIA_VERSION: "v1.2.3" },
    });
  });

  it("stops the bots with the stack", async () => {
    readConfig.mockReturnValue({ bots: ["slack"] });
    const repo = mkdtempSync(path.join(tmpdir(), "gaia-stop-"));
    mkdirSync(path.join(repo, "apps", "api"), { recursive: true });
    writeFileSync(
      path.join(repo, "apps", "api", ".env"),
      "SETUP_MODE=selfhost\n",
    );

    await stopServices(repo);
    rmSync(repo, { recursive: true, force: true });

    expect(filesIn(spawn.mock.calls[0]?.[1] as string[])).toContain(
      "docker-compose.bot-slack.yml",
    );
  });
});

describe("stopServices never reports a stop that did not happen", () => {
  beforeEach(resetMocks);

  function selfhostRepo(): string {
    const repo = mkdtempSync(path.join(tmpdir(), "gaia-stop-"));
    mkdirSync(path.join(repo, "apps", "api"), { recursive: true });
    writeFileSync(
      path.join(repo, "apps", "api", ".env"),
      "SETUP_MODE=selfhost\n",
    );
    return repo;
  }

  it("fails with the Docker problem when the socket refuses the user", async () => {
    getDockerAccess.mockResolvedValue("no-permission");
    readConfig.mockReturnValue({});
    const repo = selfhostRepo();

    await expect(stopServices(repo)).rejects.toThrow(
      "Docker is running, but your user can't use it yet",
    );
    rmSync(repo, { recursive: true, force: true });
    expect(spawn).not.toHaveBeenCalled();
  });

  it("fails when compose down fails instead of swallowing it", async () => {
    readConfig.mockReturnValue({});
    spawn.mockImplementation(() => {
      const proc = Object.assign(new EventEmitter(), {
        stdout: new EventEmitter(),
        stderr: new EventEmitter(),
        kill: vi.fn(),
      });
      setImmediate(() => {
        proc.stderr.emit("data", Buffer.from("network gaia in use\n"));
        proc.emit("close", 1);
      });
      return proc;
    });
    const repo = selfhostRepo();

    await expect(stopServices(repo)).rejects.toThrow("network gaia in use");
    rmSync(repo, { recursive: true, force: true });
  });
});

describe("startServices code-sandbox isolation", () => {
  beforeEach(resetMocks);

  it("refuses to start the sandbox on an engine that cannot isolate users", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });
    assertEngineSupportsCodeSandbox.mockRejectedValue(
      new Error("needs Docker Engine 26"),
    );

    await expect(startSelfhost()).rejects.toThrow("Docker Engine 26");
    expect(runCompose).not.toHaveBeenCalled();
  });

  it("never checks the engine when the sandbox is off", async () => {
    readConfig.mockReturnValue({});

    await startSelfhost();

    expect(assertEngineSupportsCodeSandbox).not.toHaveBeenCalled();
  });

  it("migrates the shared sandbox volume read-only after the stack is up", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });
    dockerVolumeExists.mockResolvedValue(true);

    await startSelfhost();

    expect(dockerVolumeExists).toHaveBeenCalledWith("gaia-sandbox-workspace");
    const migrate = spawn.mock.calls[0]?.[1] as string[];
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
    expect(composeArgs()).toContain("up");
    expect(runCompose.mock.invocationCallOrder[0]).toBeLessThan(
      spawn.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("runs no migration once the shared volume is gone", async () => {
    readConfig.mockReturnValue({ codeSandbox: true });

    await startSelfhost();

    expect(spawn).not.toHaveBeenCalled();
  });
});

describe("startServices never builds from source unless asked", () => {
  beforeEach(() => {
    resetMocks();
    readConfig.mockReturnValue({});
  });

  it("forbids compose from building a missing image on a pull start", async () => {
    await startSelfhost({ pull: "missing" });

    expect(composeArgs()).toContain("--no-build");
    expect(composeArgs()).not.toContain("--build");
  });

  it("builds only when --build was asked for", async () => {
    await startSelfhost({ build: true });

    expect(composeArgs()).toContain("--build");
    expect(composeArgs()).not.toContain("--no-build");
  });

  it("names the command that builds, for a missing-image error", async () => {
    await startSelfhost({ pull: "missing", rebuildCommand: "gaia up --build" });

    expect(runCompose.mock.calls[0]?.[1]).toMatchObject({
      rebuildCommand: "gaia up --build",
    });
  });
});
