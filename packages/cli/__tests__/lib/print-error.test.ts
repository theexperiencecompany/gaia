import { afterEach, describe, expect, it, vi } from "vitest";
import { runAction } from "../../src/lib/command-action.js";
import { printError } from "../../src/lib/print-error.js";

/** Everything written to stderr while fn runs. */
async function stderrOf(fn: () => unknown): Promise<string> {
  let text = "";
  vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
    text += String(chunk);
    return true;
  });
  await fn();
  return text;
}

describe("printError", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("marks the cause and indents what follows, with no 'Error:' prefix", async () => {
    const text = await stderrOf(() =>
      printError("No GAIA installation found.\nRun 'gaia up' to install it."),
    );

    expect(text).toBe(
      "  ✗ No GAIA installation found.\n    Run 'gaia up' to install it.\n",
    );
  });

  it("is how a failed command action reports, before it exits 1", async () => {
    const exit = vi
      .spyOn(process, "exit")
      .mockImplementation(() => undefined as never);

    const text = await stderrOf(() =>
      runAction(async () => {
        throw new Error("Telegram rejected the bot token.");
      }),
    );

    expect(text).toBe("  ✗ Telegram rejected the bot token.\n");
    expect(exit).toHaveBeenCalledWith(1);
  });
});
