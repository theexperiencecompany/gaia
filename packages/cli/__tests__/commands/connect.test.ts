import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "9.9.9" }));

vi.mock("node:os", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:os")>()),
  homedir: () => "/mock-home",
}));

const fsMock = vi.hoisted(() => ({
  access: vi.fn(),
  mkdir: vi.fn(),
  writeFile: vi.fn(),
  chmod: vi.fn(),
  rename: vi.fn(),
  rm: vi.fn(),
}));
vi.mock("node:fs/promises", () => ({ ...fsMock, default: fsMock }));

const spawnMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({ spawn: spawnMock }));

import {
  assetUrl,
  binaryPath,
  CONNECT_RELEASE_TAG,
  resolveAssetName,
} from "../../src/commands/connect/asset.js";
import {
  digestForAsset,
  ensureConnectBinary,
} from "../../src/commands/connect/binary.js";
import { runConnectBinary } from "../../src/commands/connect/run.js";

const BINARY_BYTES = Buffer.from("fake gaia-connect binary");
const BINARY_SHA = createHash("sha256").update(BINARY_BYTES).digest("hex");

function mockRelease(bytes: Buffer, checksums: string): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("SHA256SUMS")
        ? Buffer.from(checksums)
        : Buffer.from(bytes);
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        arrayBuffer: async () => body,
      };
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  fsMock.access.mockRejectedValue(new Error("ENOENT"));
  fsMock.mkdir.mockResolvedValue(undefined);
  fsMock.writeFile.mockResolvedValue(undefined);
  fsMock.chmod.mockResolvedValue(undefined);
  fsMock.rename.mockResolvedValue(undefined);
  fsMock.rm.mockResolvedValue(undefined);
});

describe("resolveAssetName", () => {
  it.each([
    ["darwin", "arm64", "gaia-connect-darwin-arm64"],
    ["darwin", "x64", "gaia-connect-darwin-amd64"],
    ["linux", "x64", "gaia-connect-linux-amd64"],
    ["linux", "arm64", "gaia-connect-linux-arm64"],
    ["win32", "x64", "gaia-connect-windows-amd64.exe"],
  ])("maps %s/%s to %s", (platform, arch, expected) => {
    expect(resolveAssetName(platform, arch)).toBe(expected);
  });

  it("fails loudly and names the supported targets for an unsupported pair", () => {
    expect(() => resolveAssetName("win32", "arm64")).toThrowError(
      /win32\/arm64.*darwin-arm64.*linux-arm64/s,
    );
  });
});

describe("release layout", () => {
  it("downloads from the CLI's own release tag", () => {
    expect(CONNECT_RELEASE_TAG).toBe("cli-v9.9.9");
    expect(assetUrl("gaia-connect-linux-amd64")).toBe(
      "https://github.com/theexperiencecompany/gaia/releases/download/cli-v9.9.9/gaia-connect-linux-amd64",
    );
  });

  it("caches the binary per CLI version under ~/.gaia/bin", () => {
    expect(binaryPath("darwin")).toBe(
      "/mock-home/.gaia/bin/gaia-connect-9.9.9",
    );
  });

  it("appends .exe on Windows", () => {
    expect(binaryPath("win32")).toBe(
      "/mock-home/.gaia/bin/gaia-connect-9.9.9.exe",
    );
  });
});

describe("digestForAsset", () => {
  it("picks the line for the requested asset", () => {
    const sums = `aaa  gaia-connect-linux-amd64\nbbb  gaia-connect-darwin-arm64\n`;
    expect(digestForAsset(sums, "gaia-connect-darwin-arm64")).toBe("bbb");
  });

  it("throws when the asset has no entry", () => {
    expect(() =>
      digestForAsset("aaa  other\n", "gaia-connect-linux-arm64"),
    ).toThrowError(/no entry for gaia-connect-linux-arm64/);
  });
});

describe("ensureConnectBinary", () => {
  it("installs the binary executable when the checksum matches", async () => {
    mockRelease(BINARY_BYTES, `${BINARY_SHA}  gaia-connect-linux-amd64\n`);

    const result = await ensureConnectBinary("linux", "x64");

    expect(result).toBe("/mock-home/.gaia/bin/gaia-connect-9.9.9");
    expect(fsMock.writeFile).toHaveBeenCalledWith(
      expect.stringContaining("gaia-connect-9.9.9"),
      BINARY_BYTES,
    );
    expect(fsMock.chmod).toHaveBeenCalledWith(expect.any(String), 0o700);
    expect(fsMock.rename).toHaveBeenCalledWith(
      expect.any(String),
      "/mock-home/.gaia/bin/gaia-connect-9.9.9",
    );
  });

  it("rejects a tampered download and writes nothing", async () => {
    mockRelease(
      Buffer.from("malicious payload"),
      `${BINARY_SHA}  gaia-connect-linux-amd64\n`,
    );

    await expect(ensureConnectBinary("linux", "x64")).rejects.toThrowError(
      /Checksum mismatch/,
    );
    expect(fsMock.writeFile).not.toHaveBeenCalled();
    expect(fsMock.rename).not.toHaveBeenCalled();
  });

  it("reuses the cached binary without downloading", async () => {
    fsMock.access.mockResolvedValue(undefined);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await expect(ensureConnectBinary("darwin", "arm64")).resolves.toBe(
      "/mock-home/.gaia/bin/gaia-connect-9.9.9",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("surfaces an HTTP failure instead of running unverified bytes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, statusText: "Not Found" })),
    );

    await expect(ensureConnectBinary("linux", "x64")).rejects.toThrowError(
      /404/,
    );
    expect(fsMock.writeFile).not.toHaveBeenCalled();
  });
});

interface FakeChild extends EventEmitter {
  kill: ReturnType<typeof vi.fn>;
}

function fakeChild(): FakeChild {
  const child = new EventEmitter() as FakeChild;
  child.kill = vi.fn();
  return child;
}

describe("runConnectBinary", () => {
  it("forwards every argument untouched and inherits stdio", async () => {
    const child = fakeChild();
    spawnMock.mockReturnValue(child);
    const args = ["--token", "ABC", "--api", "http://localhost:8510", "--json"];

    const done = runConnectBinary("/bin/gaia-connect", args);
    child.emit("close", 0, null);
    await expect(done).resolves.toBe(0);

    expect(spawnMock).toHaveBeenCalledWith("/bin/gaia-connect", args, {
      stdio: "inherit",
      shell: false,
    });
  });

  it("propagates a non-zero exit code", async () => {
    const child = fakeChild();
    spawnMock.mockReturnValue(child);

    const done = runConnectBinary("/bin/gaia-connect", []);
    child.emit("close", 7, null);
    await expect(done).resolves.toBe(7);
  });

  it("treats Ctrl-C on the TUI as a clean exit", async () => {
    const child = fakeChild();
    spawnMock.mockReturnValue(child);

    const done = runConnectBinary("/bin/gaia-connect", []);
    child.emit("close", null, "SIGINT");
    await expect(done).resolves.toBe(0);
  });

  it("rejects when the binary cannot be executed", async () => {
    const child = fakeChild();
    spawnMock.mockReturnValue(child);

    const done = runConnectBinary("/bin/gaia-connect", []);
    child.emit("error", new Error("EACCES"));
    await expect(done).rejects.toThrowError(/EACCES/);
  });
});
