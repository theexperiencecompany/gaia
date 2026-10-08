/**
 * `posthog.init` runs at browser idle time, up to four seconds after the page
 * loads, and `posthog.capture` before that point is dropped with nothing but a
 * console error. Every event at the head of the onboarding funnel fires inside
 * that window, so they have to survive it.
 */

import { parseUserId } from "@gaia/shared/analytics/identity";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { posthogMock, capture, identify, setPersonProperties } = vi.hoisted(
  () => {
    const capture = vi.fn();
    const identify = vi.fn();
    const setPersonProperties = vi.fn();
    return {
      capture,
      identify,
      setPersonProperties,
      posthogMock: {
        __loaded: false,
        capture,
        identify,
        setPersonProperties,
        reset: vi.fn(),
      },
    };
  },
);

vi.mock("posthog-js", () => ({ default: posthogMock }));

import { flushPendingAnalytics, identifyUser, track } from "@/lib/analytics";

const USER_ID = "6812f0b3c9a14e2b7d5a91cc";

beforeEach(() => {
  posthogMock.__loaded = false;
  capture.mockClear();
  identify.mockClear();
  setPersonProperties.mockClear();
  flushPendingAnalytics();
});

describe("analytics buffering before posthog.init", () => {
  it("replays identify and events in order once posthog is ready", () => {
    identifyUser(parseUserId(USER_ID), { email: "a@b.co" });
    track("onboarding:started", { has_saved_state: false });
    expect(identify).not.toHaveBeenCalled();
    expect(capture).not.toHaveBeenCalled();

    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(identify).toHaveBeenCalledWith(
      USER_ID,
      expect.objectContaining({ email: "a@b.co" }),
    );
    expect(capture).toHaveBeenCalledWith(
      "onboarding:started",
      expect.objectContaining({ has_saved_state: false }),
    );
    // Identity has to land before the event it attributes.
    expect(identify.mock.invocationCallOrder[0]).toBeLessThan(
      capture.mock.invocationCallOrder[0],
    );
  });

  it("keeps the event's own time, not the flush time", () => {
    track("onboarding:started", { has_saved_state: false });
    const queuedAt = new Date().toISOString();

    posthogMock.__loaded = true;
    flushPendingAnalytics();

    const [, properties] = capture.mock.calls[0] as [
      string,
      { timestamp: string },
    ];
    expect(properties.timestamp <= queuedAt).toBe(true);
  });

  it("sends straight through once initialised, and replays nothing twice", () => {
    posthogMock.__loaded = true;
    track("onboarding:started", { has_saved_state: false });
    flushPendingAnalytics();

    expect(capture).toHaveBeenCalledTimes(1);
  });
});
