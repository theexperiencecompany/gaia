/**
 * The chosen self-host server survives a restart, and a hand-edited settings
 * file can never make the window load something that is not an http(s) origin.
 * Runs the real settings module against a temp userData dir.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let userData = "";

vi.mock("electron", () => ({
  app: { getPath: () => userData },
}));

async function freshSettings(): Promise<typeof import("../src/main/settings")> {
  vi.resetModules();
  return import("../src/main/settings");
}

function writeStored(raw: Record<string, unknown>): void {
  writeFileSync(join(userData, "desktop-settings.json"), JSON.stringify(raw));
}

beforeEach(() => {
  userData = mkdtempSync(join(tmpdir(), "gaia-desktop-settings-"));
});

afterEach(() => {
  rmSync(userData, { recursive: true, force: true });
});

describe("selfHostOrigin persistence", () => {
  it("defaults to GAIA Cloud", async () => {
    const { getDesktopSettings } = await freshSettings();
    expect(getDesktopSettings().selfHostOrigin).toBeNull();
  });

  it("survives a restart", async () => {
    const first = await freshSettings();
    first.updateDesktopSettings({ selfHostOrigin: "https://gaia.example.com" });

    const second = await freshSettings();
    expect(second.getDesktopSettings().selfHostOrigin).toBe(
      "https://gaia.example.com",
    );
    expect(
      JSON.parse(readFileSync(join(userData, "desktop-settings.json"), "utf-8"))
        .selfHostOrigin,
    ).toBe("https://gaia.example.com");
  });

  it("switching back to GAIA Cloud persists", async () => {
    writeStored({ selfHostOrigin: "https://gaia.example.com" });
    const first = await freshSettings();
    first.updateDesktopSettings({ selfHostOrigin: null });

    const second = await freshSettings();
    expect(second.getDesktopSettings().selfHostOrigin).toBeNull();
  });

  it("reduces a stored address to its origin", async () => {
    writeStored({ selfHostOrigin: "https://gaia.example.com/c?x=1" });
    const { getDesktopSettings } = await freshSettings();
    expect(getDesktopSettings().selfHostOrigin).toBe(
      "https://gaia.example.com",
    );
  });

  it.each([["javascript:alert(1)"], ["file:///etc/passwd"], [42], [""]])(
    "ignores a tampered value %j",
    async (value) => {
      writeStored({ selfHostOrigin: value });
      const { getDesktopSettings } = await freshSettings();
      expect(getDesktopSettings().selfHostOrigin).toBeNull();
    },
  );
});
