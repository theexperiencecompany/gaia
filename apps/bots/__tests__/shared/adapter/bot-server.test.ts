/**
 * The deploy workflow reads `commit` off each bot's public `/health` and fails
 * the deploy when it is not the commit of the image it just rolled out.
 */

import { BotServer } from "@gaia/shared/bots";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("BotServer /health", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reports the short commit the image was built from", async () => {
    vi.stubEnv("GIT_COMMIT_SHA", "0123456789abcdef0123456789abcdef01234567");

    const response = await new BotServer("discord", 0).app.request("/health");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "ok",
      platform: "discord",
      commit: "01234567",
    });
  });
});
