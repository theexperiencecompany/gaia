import * as fs from "node:fs";
import * as os from "node:os";
import { execa } from "execa";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn }));
vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  return { ...actual, platform: vi.fn(() => "linux") };
});
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return {
    ...actual,
    promises: { ...actual.promises, access: vi.fn() },
  };
});

import { relaunchIfDockerGroupPending } from "../../src/lib/docker-group.js";

const mockedExeca = vi.mocked(execa);
const mockedAccess = vi.mocked(fs.promises.access);

const REFUSED = Object.assign(new Error("EACCES: permission denied"), {
  code: "EACCES",
});

/** `id -nG` lists these groups; `command -v sg` finds sg when hasSg. */
function system(groups: string, hasSg = true): void {
  mockedExeca.mockImplementation(((cmd: string, args: string[]) => {
    if (cmd === "id") return Promise.resolve({ stdout: groups });
    if (cmd === "sh" && args.includes("sg")) {
      return hasSg
        ? Promise.resolve({ stdout: "/usr/bin/sg" })
        : Promise.reject(new Error("exit 1"));
    }
    return Promise.reject(new Error(`unexpected ${cmd}`));
  }) as unknown as typeof execa);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(os.platform).mockReturnValue("linux");
  spawn.mockReturnValue({ on: vi.fn() });
  vi.stubEnv("GAIA_DOCKER_GROUP_RELAUNCHED", "");
  vi.stubEnv("DOCKER_HOST", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("a command in a login session older than the user's docker group", () => {
  it("re-runs itself through sg, the same way gaia up does", async () => {
    mockedAccess.mockRejectedValue(REFUSED);
    system("aryan sudo docker");

    void relaunchIfDockerGroupPending();
    await vi.waitFor(() => expect(spawn).toHaveBeenCalled());

    const [file, args, options] = spawn.mock.lastCall as [
      string,
      string[],
      { env: NodeJS.ProcessEnv },
    ];
    expect(file).toBe("sg");
    expect(args.slice(0, 2)).toEqual(["docker", "-c"]);
    expect(args[2]).toContain(process.execPath);
    expect(options.env.GAIA_DOCKER_GROUP_RELAUNCHED).toBe("1");
    expect(options.env.GAIA_RESUMED_STEP).toBeUndefined();
  });

  it("runs as it is when Docker's socket lets this session in", async () => {
    mockedAccess.mockResolvedValue(undefined);
    system("aryan sudo docker");

    await relaunchIfDockerGroupPending();

    expect(spawn).not.toHaveBeenCalled();
  });

  it("runs as it is when the user is not in the docker group at all", async () => {
    mockedAccess.mockRejectedValue(REFUSED);
    system("aryan sudo");

    await relaunchIfDockerGroupPending();

    expect(spawn).not.toHaveBeenCalled();
  });

  it("runs as it is when there is no Docker socket", async () => {
    mockedAccess.mockRejectedValue(
      Object.assign(new Error("ENOENT"), { code: "ENOENT" }),
    );
    system("aryan docker");

    await relaunchIfDockerGroupPending();

    expect(spawn).not.toHaveBeenCalled();
  });

  it("never relaunches a second time", async () => {
    vi.stubEnv("GAIA_DOCKER_GROUP_RELAUNCHED", "1");
    mockedAccess.mockRejectedValue(REFUSED);
    system("aryan docker");

    await relaunchIfDockerGroupPending();

    expect(spawn).not.toHaveBeenCalled();
  });

  it("leaves Docker's own error to explain when neither sg nor sudo can switch", async () => {
    mockedAccess.mockRejectedValue(REFUSED);
    system("aryan docker", false);

    await relaunchIfDockerGroupPending();

    expect(spawn).not.toHaveBeenCalled();
  });
});
