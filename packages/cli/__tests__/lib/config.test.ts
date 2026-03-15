import * as fs from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("fs");

// Must mock before importing config, since config.ts reads os.homedir() at
// module level to build GAIA_CONFIG_DIR / CONFIG_PATH.
vi.mock("os", () => ({
  homedir: () => "/mock-home",
}));

// version.ts uses createRequire which is hard to mock — stub the module.
vi.mock("../../src/lib/version.js", () => ({
  CLI_VERSION: "0.0.1-test",
}));

import type { GaiaConfig } from "../../src/lib/config.js";
// Import after mocks are registered so the module picks them up.
import {
  CONFIG_PATH,
  GAIA_CONFIG_DIR,
  readConfig,
  updateConfig,
  writeConfig,
} from "../../src/lib/config.js";

const mockedFs = vi.mocked(fs);

function makeSampleConfig(overrides?: Partial<GaiaConfig>): GaiaConfig {
  return {
    version: "0.0.1-test",
    setupComplete: true,
    setupMethod: "manual",
    repoPath: "/some/path",
    createdAt: "2025-01-01T00:00:00.000Z",
    updatedAt: "2025-01-01T00:00:00.000Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// readConfig
// ---------------------------------------------------------------------------
describe("readConfig", () => {
  it("returns null when config file does not exist", () => {
    mockedFs.existsSync.mockReturnValue(false);

    const result = readConfig();

    expect(result).toBeNull();
    expect(mockedFs.existsSync).toHaveBeenCalledWith(CONFIG_PATH);
  });

  it("returns parsed config when file exists", () => {
    const config = makeSampleConfig();
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.readFileSync.mockReturnValue(JSON.stringify(config));

    const result = readConfig();

    expect(result).toEqual(config);
    expect(mockedFs.readFileSync).toHaveBeenCalledWith(CONFIG_PATH, "utf-8");
  });

  it("returns null on parse error (corrupted JSON)", () => {
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.readFileSync.mockReturnValue("{not valid json!!!");

    const result = readConfig();

    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// writeConfig
// ---------------------------------------------------------------------------
describe("writeConfig", () => {
  it("creates config directory if it does not exist", () => {
    mockedFs.existsSync.mockReturnValue(false);
    mockedFs.mkdirSync.mockReturnValue(undefined);
    mockedFs.writeFileSync.mockReturnValue(undefined);

    const config = makeSampleConfig();
    writeConfig(config);

    expect(mockedFs.mkdirSync).toHaveBeenCalledWith(GAIA_CONFIG_DIR, {
      recursive: true,
    });
  });

  it("writes JSON with 2-space indent and trailing newline", () => {
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.writeFileSync.mockReturnValue(undefined);

    const config = makeSampleConfig();
    writeConfig(config);

    const expectedContent = `${JSON.stringify(config, null, 2)}\n`;
    expect(mockedFs.writeFileSync).toHaveBeenCalledWith(
      CONFIG_PATH,
      expectedContent,
    );
  });

  it("writes the correct data", () => {
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.writeFileSync.mockReturnValue(undefined);

    const config = makeSampleConfig({ repoPath: "/custom/path" });
    writeConfig(config);

    const writtenJson = mockedFs.writeFileSync.mock.calls[0]?.[1] as string;
    const parsed = JSON.parse(writtenJson);
    expect(parsed.repoPath).toBe("/custom/path");
    expect(parsed.version).toBe("0.0.1-test");
  });
});

// ---------------------------------------------------------------------------
// updateConfig
// ---------------------------------------------------------------------------
describe("updateConfig", () => {
  it("merges partial into existing config", () => {
    const existing = makeSampleConfig({ setupComplete: false });
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.readFileSync.mockReturnValue(JSON.stringify(existing));
    mockedFs.writeFileSync.mockReturnValue(undefined);

    updateConfig({ setupComplete: true });

    const writtenJson = (mockedFs.writeFileSync as ReturnType<typeof vi.fn>)
      .mock.calls[0]?.[1] as string;
    const parsed = JSON.parse(writtenJson);
    expect(parsed.setupComplete).toBe(true);
    // Original values preserved
    expect(parsed.repoPath).toBe("/some/path");
  });

  it("creates new config when none exists", () => {
    // First existsSync for readConfig -> false, then for ensureConfigDir -> false
    mockedFs.existsSync.mockReturnValue(false);
    mockedFs.mkdirSync.mockReturnValue(undefined);
    mockedFs.writeFileSync.mockReturnValue(undefined);

    updateConfig({ repoPath: "/new/repo" });

    const writtenJson = mockedFs.writeFileSync.mock.calls[0]?.[1] as string;
    const parsed = JSON.parse(writtenJson);
    expect(parsed.repoPath).toBe("/new/repo");
    expect(parsed.version).toBe("0.0.1-test");
    expect(parsed.setupComplete).toBe(false);
  });

  it("always updates the updatedAt field", () => {
    const existing = makeSampleConfig({
      updatedAt: "2020-01-01T00:00:00.000Z",
    });
    mockedFs.existsSync.mockReturnValue(true);
    mockedFs.readFileSync.mockReturnValue(JSON.stringify(existing));
    mockedFs.writeFileSync.mockReturnValue(undefined);

    const before = new Date().toISOString();
    updateConfig({ setupComplete: true });
    const after = new Date().toISOString();

    const writtenJson = (mockedFs.writeFileSync as ReturnType<typeof vi.fn>)
      .mock.calls[0]?.[1] as string;
    const parsed = JSON.parse(writtenJson);
    expect(parsed.updatedAt >= before).toBe(true);
    expect(parsed.updatedAt <= after).toBe(true);
  });
});
