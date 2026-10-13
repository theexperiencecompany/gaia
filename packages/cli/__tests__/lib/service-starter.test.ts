import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { spawn, readConfig } = vi.hoisted(() => ({
  spawn: vi.fn(),
  readConfig: vi.fn(),
}));
vi.mock("child_process", () => ({ spawn }));
vi.mock("../../src/lib/config.js", () => ({
  readConfig,
  updateConfig: vi.fn(),
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

describe("startServices compose files", () => {
  beforeEach(() => {
    spawn.mockReset();
    spawn.mockImplementation(exitingProcess);
    readConfig.mockReset();
  });

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
