// @vitest-environment jsdom

import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FOCUS_HEARTBEAT_INTERVAL_MS, FOCUS_INPUT_IDLE_MS } from "../constants";
import { useFocusHeartbeat } from "./useFocusHeartbeat";

const holdFocus = vi.fn();
const releaseFocus = vi.fn();

vi.mock("../api/presenceApi", () => ({
  presenceApi: {
    holdFocus: (clientId: string) => holdFocus(clientId),
    releaseFocus: (clientId: string) => releaseFocus(clientId),
  },
}));

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

function setWindowFocus(focused: boolean) {
  vi.spyOn(document, "hasFocus").mockReturnValue(focused);
  window.dispatchEvent(new Event(focused ? "focus" : "blur"));
}

const advance = (ms: number) => vi.advanceTimersByTime(ms);

describe("useFocusHeartbeat", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    holdFocus.mockReset().mockResolvedValue(undefined);
    releaseFocus.mockReset().mockResolvedValue(undefined);
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("reports at once when the app is visible, focused and just opened", () => {
    renderHook(() => useFocusHeartbeat(true));

    expect(holdFocus).toHaveBeenCalledTimes(1);
  });

  it("beats on every interval while the user keeps using it", () => {
    renderHook(() => useFocusHeartbeat(true));

    for (let beat = 0; beat < 2; beat++) {
      window.dispatchEvent(new Event("keydown"));
      advance(FOCUS_HEARTBEAT_INTERVAL_MS);
    }

    expect(holdFocus).toHaveBeenCalledTimes(3);
  });

  it("names the tab on every beat and on leaving, and a second tab names itself differently", () => {
    const first = renderHook(() => useFocusHeartbeat(true));
    advance(FOCUS_HEARTBEAT_INTERVAL_MS);
    first.unmount();
    renderHook(() => useFocusHeartbeat(true));

    const [firstBeat, secondBeat, secondTabBeat] = holdFocus.mock.calls.map(
      ([clientId]) => clientId,
    );
    expect(firstBeat).toEqual(secondBeat);
    expect(releaseFocus).toHaveBeenCalledWith(firstBeat);
    expect(secondTabBeat).not.toEqual(firstBeat);
  });

  it("never reports a tab open in the background", () => {
    setVisibility("hidden");
    renderHook(() => useFocusHeartbeat(true));

    window.dispatchEvent(new Event("keydown"));
    advance(3 * FOCUS_HEARTBEAT_INTERVAL_MS);

    expect(holdFocus).not.toHaveBeenCalled();
    expect(releaseFocus).not.toHaveBeenCalled();
  });

  it("never reports a window that is not focused", () => {
    setWindowFocus(false);
    renderHook(() => useFocusHeartbeat(true));

    advance(FOCUS_HEARTBEAT_INTERVAL_MS);

    expect(holdFocus).not.toHaveBeenCalled();
  });

  it("says it has left as soon as the tab is hidden, and stops beating", () => {
    renderHook(() => useFocusHeartbeat(true));

    setVisibility("hidden");
    advance(3 * FOCUS_HEARTBEAT_INTERVAL_MS);

    expect(releaseFocus).toHaveBeenCalledTimes(1);
    expect(holdFocus).toHaveBeenCalledTimes(1);
  });

  it("says it has left when the window loses focus, and reports again when it returns", () => {
    renderHook(() => useFocusHeartbeat(true));

    setWindowFocus(false);
    setWindowFocus(true);
    window.dispatchEvent(new Event("keydown"));

    expect(releaseFocus).toHaveBeenCalledTimes(1);
    expect(holdFocus).toHaveBeenCalledTimes(2);
  });

  it("stops reporting a focused window nobody has touched for a while", () => {
    renderHook(() => useFocusHeartbeat(true));

    advance(FOCUS_INPUT_IDLE_MS + FOCUS_HEARTBEAT_INTERVAL_MS);

    expect(releaseFocus).toHaveBeenCalledTimes(1);
    const beatsBeforeIdle = holdFocus.mock.calls.length;
    advance(5 * FOCUS_HEARTBEAT_INTERVAL_MS);
    expect(holdFocus).toHaveBeenCalledTimes(beatsBeforeIdle);
  });

  it("reports again as soon as an idle user touches the pointer", () => {
    renderHook(() => useFocusHeartbeat(true));
    advance(FOCUS_INPUT_IDLE_MS + FOCUS_HEARTBEAT_INTERVAL_MS);
    const beatsBeforeReturn = holdFocus.mock.calls.length;

    window.dispatchEvent(new Event("pointermove"));

    expect(holdFocus).toHaveBeenCalledTimes(beatsBeforeReturn + 1);
  });

  it("says it has left when the app unmounts, and reports nothing disabled", () => {
    const { unmount } = renderHook(() => useFocusHeartbeat(true));
    unmount();
    expect(releaseFocus).toHaveBeenCalledTimes(1);

    holdFocus.mockClear();
    renderHook(() => useFocusHeartbeat(false));
    advance(FOCUS_HEARTBEAT_INTERVAL_MS);
    expect(holdFocus).not.toHaveBeenCalled();
  });

  it("surfaces a failed beat instead of swallowing it", async () => {
    const failure = new Error("offline");
    holdFocus.mockRejectedValue(failure);
    const logged = vi.spyOn(console, "error").mockImplementation(() => {
      // The failure is asserted on below.
    });

    renderHook(() => useFocusHeartbeat(true));
    await vi.advanceTimersByTimeAsync(0);

    expect(logged).toHaveBeenCalledWith(
      "[FocusHeartbeat] Failed to report focus",
      failure,
    );
  });
});
