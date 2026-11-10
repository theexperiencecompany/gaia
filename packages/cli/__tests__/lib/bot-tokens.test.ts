import { afterEach, describe, expect, it, vi } from "vitest";
import { verifyTelegramToken } from "../../src/lib/bot-tokens.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("verifyTelegramToken", () => {
  it("names the platform's reason when it rejects the token", async () => {
    vi.stubGlobal("fetch", async () =>
      Response.json(
        { ok: false, error_code: 401, description: "Unauthorized" },
        { status: 401 },
      ),
    );

    await expect(verifyTelegramToken("bad")).rejects.toThrow(
      "Telegram rejected the bot token: Unauthorized. Copy it again from @BotFather.",
    );
  });

  it("reports an outage page as the HTTP status, not a JSON parse error", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response("<html>Bad gateway</html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
    );

    await expect(verifyTelegramToken("t")).rejects.toThrow(
      "api.telegram.org answered HTTP 502. Try again in a minute.",
    );
  });

  it("returns the bot's username for a valid token", async () => {
    vi.stubGlobal("fetch", async () =>
      Response.json({ ok: true, result: { username: "my_gaia_bot" } }),
    );

    await expect(verifyTelegramToken("t")).resolves.toBe("my_gaia_bot");
  });
});
