/**
 * PostHog identity resolution in `BaseBotAdapter`.
 *
 * A bot event must land on the same PostHog profile as the user's web and API
 * events. The backend already attributes bot chat turns to the stable GAIA user
 * id (`bot.py::chat`), so keying bot-process events on `<platform>:<id>` split
 * every user into two people. These tests pin the resolution, the alias that
 * stitches the pre-link history, and the failure fallback.
 */

import { BaseBotAdapter } from "@gaia/shared/bots";
import { beforeEach, describe, expect, it, vi } from "vitest";

const PLATFORM_USER_ID = "123456789";
const PLATFORM_DISTINCT_ID = "discord:123456789";
const GAIA_USER_ID = "68f0a1b2c3d4e5f6a7b8c9d0";

/** Concrete adapter exposing the protected identity helpers to the test. */
class TestAdapter extends BaseBotAdapter {
  readonly platform = "discord" as const;
  protected readonly defaultServerPort = 3200;

  // The abstract lifecycle contract, stubbed: these tests drive identity
  // resolution directly and never boot a platform client.
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
  buildContext() {
    return {} as never;
  }

  /** Test seam for the two protected collaborators `boot()` would install. */
  install(gaia: unknown, analytics: unknown): void {
    (this as unknown as { gaia: unknown }).gaia = gaia;
    (this as unknown as { analytics: unknown }).analytics = analytics;
  }

  resolve(platformUserId: string): Promise<string> {
    return this.resolveDistinctId(platformUserId);
  }
}

function setup(checkAuthStatus: ReturnType<typeof vi.fn>) {
  const analytics = { capture: vi.fn(), alias: vi.fn() };
  const adapter = new TestAdapter();
  adapter.install({ checkAuthStatus }, analytics);
  return { adapter, analytics };
}

describe("BaseBotAdapter.resolveDistinctId", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the linked GAIA user id so bot events join the web/API profile", async () => {
    const checkAuthStatus = vi.fn(async () => ({
      authenticated: true,
      platform: "discord",
      platform_user_id: PLATFORM_USER_ID,
      user_id: GAIA_USER_ID,
    }));
    const { adapter } = setup(checkAuthStatus);

    await expect(adapter.resolve(PLATFORM_USER_ID)).resolves.toBe(GAIA_USER_ID);
    expect(checkAuthStatus).toHaveBeenCalledWith("discord", PLATFORM_USER_ID);
  });

  it("aliases the pre-link platform id onto the GAIA id, oldest id first", async () => {
    const { adapter, analytics } = setup(
      vi.fn(async () => ({
        authenticated: true,
        platform: "discord",
        platform_user_id: PLATFORM_USER_ID,
        user_id: GAIA_USER_ID,
      })),
    );

    await adapter.resolve(PLATFORM_USER_ID);

    // Argument order matters: previousId then distinctId. Reversed, the merge
    // still happens but the surviving profile is the anonymous one.
    expect(analytics.alias).toHaveBeenCalledWith(
      PLATFORM_DISTINCT_ID,
      GAIA_USER_ID,
    );
  });

  it("aliases once per user, not once per message", async () => {
    const checkAuthStatus = vi.fn(async () => ({
      authenticated: true,
      platform: "discord",
      platform_user_id: PLATFORM_USER_ID,
      user_id: GAIA_USER_ID,
    }));
    const { adapter, analytics } = setup(checkAuthStatus);

    await adapter.resolve(PLATFORM_USER_ID);
    await adapter.resolve(PLATFORM_USER_ID);
    await adapter.resolve(PLATFORM_USER_ID);

    expect(analytics.alias).toHaveBeenCalledTimes(1);
    // ...and the cache spares the link lookup on every subsequent event.
    expect(checkAuthStatus).toHaveBeenCalledTimes(1);
  });

  it("falls back to the platform id while the account is unlinked", async () => {
    const { adapter, analytics } = setup(
      vi.fn(async () => ({
        authenticated: false,
        platform: "discord",
        platform_user_id: PLATFORM_USER_ID,
      })),
    );

    await expect(adapter.resolve(PLATFORM_USER_ID)).resolves.toBe(
      PLATFORM_DISTINCT_ID,
    );
    expect(analytics.alias).not.toHaveBeenCalled();
  });

  it("re-checks an unlinked user, so linking mid-process is picked up", async () => {
    const checkAuthStatus = vi
      .fn()
      .mockResolvedValueOnce({
        authenticated: false,
        platform: "discord",
        platform_user_id: PLATFORM_USER_ID,
      })
      .mockResolvedValueOnce({
        authenticated: true,
        platform: "discord",
        platform_user_id: PLATFORM_USER_ID,
        user_id: GAIA_USER_ID,
      });
    const { adapter, analytics } = setup(checkAuthStatus);

    await expect(adapter.resolve(PLATFORM_USER_ID)).resolves.toBe(
      PLATFORM_DISTINCT_ID,
    );
    await expect(adapter.resolve(PLATFORM_USER_ID)).resolves.toBe(GAIA_USER_ID);
    expect(analytics.alias).toHaveBeenCalledTimes(1);
  });

  it("degrades to the platform id when the link lookup fails", async () => {
    const { adapter, analytics } = setup(
      vi.fn(async () => {
        throw new Error("backend down");
      }),
    );

    // An event on the anonymous profile is recoverable; a dropped one is not.
    await expect(adapter.resolve(PLATFORM_USER_ID)).resolves.toBe(
      PLATFORM_DISTINCT_ID,
    );
    expect(analytics.alias).not.toHaveBeenCalled();
  });
});
