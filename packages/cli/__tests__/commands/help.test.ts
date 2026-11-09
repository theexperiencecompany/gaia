import { afterEach, describe, expect, it, vi } from "vitest";

// version.ts uses createRequire on package.json, which breaks under vitest.
vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

/** Lines with a space to break at; a lone word (a URL) longer than the column cannot wrap. */
function wrappable(lines: string[]): string[] {
  return lines.filter((line) => line.trim().includes(" "));
}

/** Commander ends `--help` with process.exit; stop there instead. */
class HelpExit extends Error {}

/** What `gaia <args>` prints on a terminal this many columns wide. */
async function helpAt(columns: number, args: string[]): Promise<string> {
  let out = "";
  vi.spyOn(process, "argv", "get").mockReturnValue(["node", "gaia", ...args]);
  Object.assign(process.stdout, { isTTY: true, columns });
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    out += String(chunk);
    return true;
  });
  vi.spyOn(process, "exit").mockImplementation(() => {
    throw new HelpExit();
  });
  await import("../../src/index.js").catch((error: unknown) => {
    if (!(error instanceof HelpExit)) throw error;
  });
  return out;
}

describe("gaia --help on a narrow terminal", () => {
  const { isTTY, columns } = process.stdout;
  afterEach(() => {
    Object.assign(process.stdout, { isTTY, columns });
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("wraps descriptions at 60 columns instead of letting the terminal split words", async () => {
    const lines = (await helpAt(60, ["--help"])).split("\n");

    for (const line of wrappable(lines))
      expect(line.length).toBeLessThanOrEqual(60);
    expect(lines.join("\n")).toContain("Telegram, Discord or");
  });

  it("wraps a command's own option help the same way", async () => {
    const lines = (await helpAt(60, ["up", "--help"])).split("\n");

    expect(lines.join("\n")).toContain("--llm-key");
    for (const line of wrappable(lines))
      expect(line.length).toBeLessThanOrEqual(60);
  });
});
