import { beforeEach, describe, expect, it, vi } from "vitest";

const execa = vi.fn();
let recorded: string | true | undefined;

vi.mock("execa", () => ({ execa: (...args: unknown[]) => execa(...args) }));
vi.mock("node:fs", async (original) => ({
  ...(await original<typeof import("node:fs")>()),
  existsSync: () => true,
}));
vi.mock("../../src/lib/config.js", async (original) => ({
  ...(await original<typeof import("../../src/lib/config.js")>()),
  readConfig: () => ({ localName: recorded }),
}));
vi.mock("../../src/lib/root-command.js", () => ({ runAsRoot: vi.fn() }));
vi.mock("../../src/lib/local-name-ipv6.js", () => ({
  currentStableIpv6: vi.fn(),
  installIpv6Publisher: vi.fn(),
  removeIpv6Publisher: vi.fn(),
}));

import { removeLocalName } from "../../src/lib/local-name.js";

/** The names removeLocalName asked portless to drop. */
function removedAliases(): unknown[] {
  return execa.mock.calls
    .map((call) => call[1] as string[])
    .filter((args) => args[1] === "alias")
    .map((args) => args[3]);
}

beforeEach(() => {
  execa.mockReset();
  execa.mockResolvedValue({ stdout: "/usr/lib/node_modules", failed: false });
});

describe("removeLocalName", () => {
  it("removes only the name this install claimed, never another GAIA's", async () => {
    recorded = "gaia-2";

    await removeLocalName();

    expect(removedAliases()).toEqual(["gaia-2"]);
  });

  it("removes gaia for an install from a CLI that recorded no name", async () => {
    recorded = true;

    await removeLocalName();

    expect(removedAliases()).toEqual(["gaia"]);
  });
});
