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
} = vi.hoisted(() => ({
  spawn: vi.fn(),
  readConfig: vi.fn(),
  assertEngineSupportsCodeSandbox: vi.fn(),
  dockerVolumeExists: vi.fn(),
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
const { writeBotsEnv } = vi.hoisted(() => ({ writeBotsEnv: vi.fn() }));
vi.mock("../../src/lib/bots.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/bots.js")>()),
  writeBotsEnv,
}));

import {
  pullSelfhostImages,
  startServices,
  stopServices,
  UnpublishedImageError,
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

/** The -f files of the Nth docker invocation. */
function composeFilesOfCall(call: number): string[] {
  const args = spawn.mock.calls[call]?.[1] as string[];
  return args.flatMap((arg, i) => (args[i - 1] === "-f" ? [arg] : []));
}

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
      spawn.mock.invocationCallOrder[0] ?? 0,
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

    expect(composeFilesOfCall(0)).toContain("docker-compose.bot-telegram.yml");
    expect(spawn.mock.calls[0]?.[1]).toEqual(
      expect.arrayContaining(["pull", "gaia-backend", "bot-telegram"]),
    );
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

    expect(composeFilesOfCall(0)).toContain("docker-compose.bot-slack.yml");
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

/** A child process that writes compose's stderr, then exits 1. */
function failingProcess(stderr: string): () => EventEmitter {
  return () => {
    const proc = Object.assign(new EventEmitter(), {
      stdout: new EventEmitter(),
      stderr: new EventEmitter(),
      kill: vi.fn(),
    });
    setImmediate(() => {
      proc.stderr.emit("data", Buffer.from(stderr));
      proc.emit("close", 1);
    });
    return proc;
  };
}

function startSelfhost(
  options?: Parameters<typeof startServices>[5],
): Promise<void> {
  return startServices(
    "/no/such/repo",
    "selfhost",
    undefined,
    undefined,
    undefined,
    options,
  );
}

describe("startServices never builds from source unless asked", () => {
  beforeEach(() => {
    resetMocks();
    readConfig.mockReturnValue({});
  });

  it("forbids compose from building a missing image on a pull start", async () => {
    await startSelfhost({ pull: "missing" });

    const args = spawn.mock.calls[0]?.[1] as string[];
    expect(args).toContain("--no-build");
    expect(args).not.toContain("--build");
  });

  it("builds only when --build was asked for", async () => {
    await startSelfhost({ build: true });

    const args = spawn.mock.calls[0]?.[1] as string[];
    expect(args).toContain("--build");
    expect(args).not.toContain("--no-build");
  });

  // Both stderr lines are verbatim from docker compose v5.5 `up --no-build`.
  it.each([
    "Error response from daemon: No such image: ghcr.io/theexperiencecompany/gaia:0.9.1-rc\n",
    'Error response from daemon: failed to resolve reference "ghcr.io/theexperiencecompany/gaia-web:0.9.1-rc": ghcr.io/theexperiencecompany/gaia-web:0.9.1-rc: not found\n',
  ])(
    "names the unpublished GAIA release instead of compose's error: %s",
    async (stderr) => {
      spawn.mockImplementation(failingProcess(stderr));

      const error = await startSelfhost({ pull: "missing" }).catch((e) => e);

      expect(error).toBeInstanceOf(UnpublishedImageError);
      expect(error.message).toMatch(
        /^GAIA 0\.9\.1-rc images aren't published \(ghcr\.io\/theexperiencecompany\/gaia(-web)?:0\.9\.1-rc\)\. Run `gaia update`, or `gaia up --build` to build from source\.$/,
      );
    },
  );

  it("keeps compose's own error when a third-party image is missing", async () => {
    spawn.mockImplementation(
      failingProcess(
        "Error response from daemon: No such image: postgres:18-alpine\n",
      ),
    );

    const error = await startSelfhost({ pull: "missing" }).catch((e) => e);

    expect(error).not.toBeInstanceOf(UnpublishedImageError);
    expect(error.message).toContain("No such image: postgres:18-alpine");
  });
});
