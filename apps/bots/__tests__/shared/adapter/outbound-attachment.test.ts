/**
 * Which transport an outbound attachment URL is fetched with.
 *
 * Step screenshots used to be R2 objects, so every attachment URL was public and
 * the SSRF-guarded public fetch was the only path. The API can now serve them
 * itself at `GET /shots/{code}/{index}.png` on GAIA's own base URL, which in
 * development is a loopback address the guard correctly refuses — so the photo
 * silently became a text caption. A URL on our own origin therefore goes through
 * the authenticated client, and everything else keeps the guard.
 *
 * Only axios and the public fetch are faked; the origin decision, `GaiaClient`
 * and `BaseBotAdapter.fetchOutboundArtifact` under test are all real.
 */

import { BaseBotAdapter } from "@gaia/shared/bots";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GaiaClient } from "../../../../../libs/shared/ts/src/bots/api";
import type { OutboundAttachment } from "../../../../../libs/shared/ts/src/bots/consumer/envelope";
import { fetchPublicAsset } from "../../../../../libs/shared/ts/src/bots/utils/public-fetch";

const API_BASE = "https://api.gaia.test";
const DESTINATION_ID = "123456789";
const PNG = Buffer.from("fake-png-bytes");

const axiosGet = vi.fn();

vi.mock("../../../../../libs/shared/ts/src/bots/utils/public-fetch", () => ({
  fetchPublicAsset: vi.fn(),
  assertIsPublicHttpsUrl: vi.fn(),
  isNonPublicAddress: vi.fn(() => false),
}));
const publicFetch = vi.mocked(fetchPublicAsset);

/** Concrete adapter exposing the protected artifact fetch to the test. */
class TestAdapter extends BaseBotAdapter {
  readonly platform = "discord" as const;
  protected readonly defaultServerPort = 3200;

  protected async initialize(): Promise<void> {
    /* no platform client under test */
  }
  protected async registerCommands(): Promise<void> {
    /* no commands under test */
  }
  protected async registerEvents(): Promise<void> {
    /* no events under test */
  }
  protected async start(): Promise<void> {
    /* nothing to connect */
  }
  protected async stop(): Promise<void> {
    /* nothing to disconnect */
  }
  protected async deliverOutbound(): Promise<void> {
    /* no outbound delivery under test */
  }
  override buildContext() {
    return {} as never;
  }

  install(gaia: GaiaClient): void {
    (this as unknown as { gaia: GaiaClient }).gaia = gaia;
    (this as unknown as { analytics: unknown }).analytics = {
      capture: vi.fn(),
      alias: vi.fn(),
    };
  }

  fetch(attachment: OutboundAttachment) {
    return this.fetchOutboundArtifact(DESTINATION_ID, attachment);
  }
}

/**
 * A real `GaiaClient` on a real axios instance — so `baseURL` is whatever the
 * constructor actually stored — with only the network call replaced.
 */
function setup(baseUrl = API_BASE) {
  const gaia = new GaiaClient(baseUrl, "bot-key", "https://app.gaia.test");
  (gaia as unknown as { client: { get: typeof axiosGet } }).client.get =
    axiosGet;
  const adapter = new TestAdapter();
  adapter.install(gaia);
  return adapter;
}

function attachment(url: string): OutboundAttachment {
  return { filename: "step-1.png", url };
}

describe("fetchOutboundArtifact URL routing", () => {
  beforeEach(() => {
    axiosGet.mockReset();
    axiosGet.mockResolvedValue({
      data: new Uint8Array(PNG).buffer,
      headers: { "content-type": "image/png" },
    });
    publicFetch.mockReset();
    publicFetch.mockResolvedValue({ data: PNG, contentType: "image/png" });
  });

  it("fetches a URL on GAIA's own API through the authenticated client", async () => {
    const adapter = setup();

    const artifact = await adapter.fetch(
      attachment(`${API_BASE}/shots/c0de/1.png`),
    );

    expect(publicFetch).not.toHaveBeenCalled();
    expect(axiosGet).toHaveBeenCalledTimes(1);
    const [, options] = axiosGet.mock.calls[0];
    expect(options.responseType).toBe("arraybuffer");
    expect(options.headers["X-Bot-API-Key"]).toBe("bot-key");
    expect(options.headers["X-Bot-Platform"]).toBe("discord");
    expect(options.headers["X-Bot-Platform-User-Id"]).toBe(DESTINATION_ID);
    // Same 100 MB transport cap as every other binary download, so the
    // per-platform OUTBOUND_FILE_LIMITS note still does the user-facing work.
    expect(options.maxContentLength).toBe(100 * 1024 * 1024);
    expect(options.maxBodyLength).toBe(100 * 1024 * 1024);
    expect(artifact?.contentType).toBe("image/png");
    expect(artifact?.data.toString()).toBe(PNG.toString());
  });

  it.each([
    ["a trailing slash on the configured base", `${API_BASE}/`],
    ["an uppercase host", "https://API.GAIA.TEST"],
    ["the default port spelled out", "https://api.gaia.test:443"],
  ])("still matches its own origin with %s", async (_label, baseUrl) => {
    const adapter = setup(baseUrl);

    await adapter.fetch(attachment(`${API_BASE}/shots/c0de/1.png`));

    expect(publicFetch).not.toHaveBeenCalled();
    expect(axiosGet).toHaveBeenCalledTimes(1);
  });

  it("keeps the SSRF-guarded public fetch for another origin", async () => {
    const adapter = setup();
    const url = "https://cdn.example.com/browser_steps/s/1.png";

    await adapter.fetch(attachment(url));

    expect(axiosGet).not.toHaveBeenCalled();
    expect(publicFetch).toHaveBeenCalledTimes(1);
    expect(publicFetch.mock.calls[0][0]).toBe(url);
  });

  it.each([
    [
      "our host as a suffixed domain",
      "https://api.gaia.test.evil.com/shots/c/1.png",
    ],
    ["our host in the path", "https://evil.com/api.gaia.test/shots/c/1.png"],
    [
      "our host in the query",
      "https://evil.com/shots/c/1.png?x=https://api.gaia.test",
    ],
    ["our host as a userinfo", "https://api.gaia.test@evil.com/shots/c/1.png"],
    ["a different port", "https://api.gaia.test:8443/shots/c/1.png"],
    ["a different scheme", "http://api.gaia.test/shots/c/1.png"],
  ])(
    "treats %s as external, so the guard still applies",
    async (_label, url) => {
      const adapter = setup();

      await adapter.fetch(attachment(url));

      expect(axiosGet).not.toHaveBeenCalled();
      expect(publicFetch).toHaveBeenCalledTimes(1);
      expect(publicFetch.mock.calls[0][0]).toBe(url);
    },
  );
});
