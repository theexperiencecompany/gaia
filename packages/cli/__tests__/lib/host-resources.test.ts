import * as fs from "node:fs";
import { execa, type ResultPromise } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, existsSync: vi.fn(() => true) };
});

import {
  DATA_DISK_MIN_BYTES,
  DATA_DISK_RECOMMENDED_BYTES,
  getDockerRootDir,
  judgeDisk,
  judgeMemory,
  MEMORY_MIN_BYTES,
  MEMORY_RECOMMENDED_BYTES,
  parseDfAvailableKb,
  RELEASE_IMAGES_DISK_BYTES,
  readDockerDiskFree,
  readDockerMemoryBytes,
} from "../../src/lib/host-resources.js";

const mockedExeca = vi.mocked(execa);
const GIB = 1024 ** 3;

function answer(stdout: string): Awaited<ResultPromise> {
  return { stdout } as Awaited<ResultPromise>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fs.existsSync).mockReturnValue(true);
});

describe("judgeDisk", () => {
  it("refuses a fresh install that cannot hold the release's images", () => {
    const verdict = judgeDisk(8 * GIB, "/var/lib/docker", "install");

    expect(verdict.level).toBe("fail");
    expect(verdict.detail).toContain("8.0 GB free at /var/lib/docker");
    expect(verdict.fix).toContain("docker system prune");
  });

  it("warns a fresh install that fits the images but leaves little for data", () => {
    const free = RELEASE_IMAGES_DISK_BYTES + DATA_DISK_MIN_BYTES;

    expect(judgeDisk(free, "/var/lib/docker", "install").level).toBe("warn");
  });

  it("passes a fresh install with room for the images and data", () => {
    const free = RELEASE_IMAGES_DISK_BYTES + DATA_DISK_RECOMMENDED_BYTES;

    expect(judgeDisk(free, "/var/lib/docker", "install").level).toBe("ok");
  });

  it("holds a running install only to room for its data", () => {
    expect(judgeDisk(8 * GIB, "/var/lib/docker", "run").level).toBe("ok");
    expect(judgeDisk(DATA_DISK_MIN_BYTES - 1, "/x", "run").level).toBe("fail");
    expect(judgeDisk(DATA_DISK_MIN_BYTES, "/x", "run").level).toBe("warn");
  });
});

describe("judgeMemory", () => {
  it("refuses less memory than the booted stack holds, naming Docker's limit on a Mac", () => {
    const verdict = judgeMemory(4 * GIB, { platform: "darwin", wsl: false });

    expect(verdict.level).toBe("fail");
    expect(verdict.detail).toContain("4.0 GB");
    expect(verdict.fix).toMatch(/Docker Desktop.*Resources/);
  });

  it("points a WSL user at .wslconfig", () => {
    const verdict = judgeMemory(4 * GIB, { platform: "linux", wsl: true });

    expect(verdict.fix).toContain(".wslconfig");
    expect(verdict.fix).toContain("wsl --shutdown");
  });

  it("warns between the minimum and the recommended size", () => {
    const verdict = judgeMemory(MEMORY_MIN_BYTES, {
      platform: "linux",
      wsl: false,
    });

    expect(verdict.level).toBe("warn");
  });

  it("passes an 8 GB machine, which reports a little under 8 GiB", () => {
    expect(
      judgeMemory(MEMORY_RECOMMENDED_BYTES, { platform: "linux", wsl: false })
        .level,
    ).toBe("ok");
  });
});

describe("parseDfAvailableKb", () => {
  it("reads the available column of the last line", () => {
    const output = [
      "Filesystem   1024-blocks     Used Available Capacity Mounted on",
      "/dev/sda1     1000000   500000    500000    50%      /",
    ].join("\n");
    expect(parseDfAvailableKb(output)).toBe(500000);
  });

  it("returns null for malformed output", () => {
    expect(parseDfAvailableKb("")).toBeNull();
    expect(parseDfAvailableKb("a b not-a-number d")).toBeNull();
  });
});

describe("getDockerRootDir", () => {
  it("asks the daemon where it keeps its data", async () => {
    mockedExeca.mockResolvedValueOnce(answer("/srv/docker\n"));

    expect(await getDockerRootDir()).toBe("/srv/docker");
    expect(mockedExeca).toHaveBeenCalledWith("docker", [
      "info",
      "--format",
      "{{.DockerRootDir}}",
    ]);
  });
});

describe("readDockerDiskFree", () => {
  it("measures the disk holding Docker's data root, not the home folder", async () => {
    mockedExeca.mockResolvedValueOnce(
      answer(
        "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/sdb 100 50 2048 50% /srv",
      ),
    );

    expect(await readDockerDiskFree("/srv/docker")).toBe(2048 * 1024);
    expect(mockedExeca).toHaveBeenCalledWith("df", ["-k", "/srv/docker"]);
  });

  it("returns null when the data root lives inside Docker's VM, instead of measuring the wrong disk", async () => {
    vi.mocked(fs.existsSync).mockReturnValue(false);

    expect(await readDockerDiskFree("/var/lib/docker")).toBeNull();
    expect(mockedExeca).not.toHaveBeenCalled();
  });

  it("fails loud on df output it cannot read", async () => {
    mockedExeca.mockResolvedValueOnce(answer("garbage"));

    await expect(readDockerDiskFree("/var/lib/docker")).rejects.toThrow(/df/);
  });
});

describe("readDockerMemoryBytes", () => {
  it("reads the memory Docker can give containers", async () => {
    mockedExeca.mockResolvedValueOnce(answer("16818118656\n"));

    expect(await readDockerMemoryBytes()).toBe(16818118656);
    expect(mockedExeca).toHaveBeenCalledWith("docker", [
      "info",
      "--format",
      "{{.MemTotal}}",
    ]);
  });

  it("fails loud on an answer that is not a size", async () => {
    mockedExeca.mockResolvedValueOnce(answer("<no value>"));

    await expect(readDockerMemoryBytes()).rejects.toThrow(/MemTotal/);
  });
});
