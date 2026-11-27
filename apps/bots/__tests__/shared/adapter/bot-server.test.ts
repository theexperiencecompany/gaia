/**
 * The deploy workflow reads `commit` off each bot's public `/health` and fails
 * the deploy when it is not the commit of the image it just rolled out.
 */

import { BotServer } from "@gaia/shared/bots";
import { afterEach, describe, expect, it, vi } from "vitest";
import { botRegistry } from "../../../../../libs/shared/ts/src/bots/metrics";

const PLATFORMS = ["discord", "slack", "telegram", "whatsapp", "imessage"];
const OUTCOMES = ["ok", "failed"];

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

describe("BotServer /metrics", () => {
  it("serves every bot series at zero before anything has happened", async () => {
    const response = await new BotServer("discord", 0).app.request("/metrics");
    const body = await response.text();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe(botRegistry.contentType);
    for (const platform of PLATFORMS) {
      for (const outcome of OUTCOMES) {
        const labels = `{platform="${platform}",outcome="${outcome}"}`;
        expect(body).toContain(`gaia_bot_inbound_total${labels} 0`);
        expect(body).toContain(`gaia_bot_outbound_total${labels} 0`);
      }
    }
    expect(body).toContain("# TYPE gaia_bot_platform_connected gauge");
    expect(body).toContain("process_cpu_user_seconds_total");
  });
});
