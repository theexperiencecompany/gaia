import { describe, expect, it } from "vitest";
import { runCommand } from "../../src/lib/service-starter.js";

/** Exits 0 only when its single argument arrives exactly as given. */
const EXPECT_ARG =
  "process.exit(process.argv[1] === process.env.EXPECTED ? 0 : 1)";

describe("runCommand", () => {
  it("passes each argument to the process verbatim, never through a shell", async () => {
    const arg = "two words; echo $HOME | cat";

    await expect(
      runCommand(
        process.execPath,
        ["-e", EXPECT_ARG, arg],
        process.cwd(),
        undefined,
        undefined,
        { EXPECTED: arg },
      ),
    ).resolves.toBeUndefined();
  });
});
