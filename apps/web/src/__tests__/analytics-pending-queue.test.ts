/**
 * `posthog.init` runs at browser idle time, up to four seconds after the page
 * loads, and `posthog.capture` before that point is dropped with nothing but a
 * console error. Every event at the head of the onboarding funnel fires inside
 * that window, so they have to survive it.
 */

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

import {
  ANALYTICS_EVENTS,
  flushPendingAnalytics,
  identifyUser,
  trackEvent,
} from "@/lib/analytics";

beforeEach(() => {
  posthogMock.__loaded = false;
  capture.mockClear();
  identify.mockClear();
  setPersonProperties.mockClear();
  flushPendingAnalytics();
});

describe("analytics buffering before posthog.init", () => {
  it("replays identify and events in order once posthog is ready", () => {
    identifyUser("user_1", { email: "a@b.co" });
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED, { has_saved_state: false });
    expect(identify).not.toHaveBeenCalled();
    expect(capture).not.toHaveBeenCalled();

    posthogMock.__loaded = true;
    flushPendingAnalytics();

    expect(identify).toHaveBeenCalledWith(
      "user_1",
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
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED);
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
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_STARTED);
    flushPendingAnalytics();

    expect(capture).toHaveBeenCalledTimes(1);
  });
});
