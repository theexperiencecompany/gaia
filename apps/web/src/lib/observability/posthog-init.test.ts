/**
 * Regression test: PostHog session replay must be enabled in code.
 *
 * The bug: `posthog.init()` in `instrumentation-client.ts` passed no
 * `session_recording` option, so the web SDK never produced `$snapshot`
 * data. Events (`$pageview`, captures) flowed normally while Replay /
 * Sessions stayed empty with `$recording_status` stuck at
 * `buffering`/`lazy_loading`, and the PostHog dashboard reported that
 * replay needs a code change to enable. This pins that init carries an
 * explicit `session_recording` block.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const initMock = vi.fn();

vi.mock("posthog-js", () => ({ default: { init: initMock } }));

describe("instrumentation-client posthog init", () => {
  beforeEach(() => {
    vi.resetModules();
    initMock.mockClear();
    vi.unstubAllGlobals();
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", "phc_test_token");
  });

  it("passes an explicit session_recording block to posthog.init", async () => {
    // instrumentation-client.ts only arms itself when `window` exists and
    // schedules loading via the bare `requestIdleCallback` global.
    // Capture the idle-time loader instead of waiting for it.
    let idleCallback: (() => void) | undefined;
    vi.stubGlobal("window", { requestIdleCallback: true });
    vi.stubGlobal("requestIdleCallback", (callback: () => void) => {
      idleCallback = callback;
    });

    await import("../../../instrumentation-client");
    expect(idleCallback).toBeDefined();

    idleCallback?.();
    await vi.waitFor(() => {
      expect(initMock).toHaveBeenCalledTimes(1);
    });

    const [token, config] = initMock.mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(token).toBe("phc_test_token");
    expect(config["disable_session_recording"]).not.toBe(true);
    expect(config["session_recording"]).toEqual({});
  });
});
