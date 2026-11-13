import { useEffect } from "react";
import { presenceApi } from "../api/presenceApi";
import {
  FOCUS_HEARTBEAT_INTERVAL_MS,
  FOCUS_INPUT_EVENTS,
  FOCUS_INPUT_IDLE_MS,
} from "../constants";

function reportFailure(action: string) {
  return (error: unknown) =>
    console.error(`[FocusHeartbeat] Failed to ${action}`, error);
}

/**
 * Tell the API the user is looking at this app, for as long as it is.
 *
 * Looking means the tab is visible, the window is focused and the keyboard or
 * pointer was used lately, so a tab left open in the background, or a focused
 * window nobody is at, is never reported. The server forgets the app one missed
 * beat after the last one, so leaving is also said at once rather than waited out.
 * Each tab names itself, so one tab leaving never clears another still in view.
 */
export function useFocusHeartbeat(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;

    const clientId = crypto.randomUUID();
    let lastInputAt = Date.now();
    let reporting = false;

    const isLooking = () =>
      document.visibilityState === "visible" &&
      document.hasFocus() &&
      Date.now() - lastInputAt <= FOCUS_INPUT_IDLE_MS;

    const evaluate = () => {
      if (isLooking()) {
        reporting = true;
        presenceApi.holdFocus(clientId).catch(reportFailure("report focus"));
      } else if (reporting) {
        reporting = false;
        presenceApi
          .releaseFocus(clientId)
          .catch(reportFailure("release focus"));
      }
    };

    const onInput = () => {
      lastInputAt = Date.now();
      if (!reporting) evaluate();
    };

    evaluate();
    const intervalId = setInterval(evaluate, FOCUS_HEARTBEAT_INTERVAL_MS);
    document.addEventListener("visibilitychange", evaluate);
    window.addEventListener("focus", evaluate);
    window.addEventListener("blur", evaluate);
    for (const event of FOCUS_INPUT_EVENTS) {
      window.addEventListener(event, onInput, { passive: true });
    }

    return () => {
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", evaluate);
      window.removeEventListener("focus", evaluate);
      window.removeEventListener("blur", evaluate);
      for (const event of FOCUS_INPUT_EVENTS) {
        window.removeEventListener(event, onInput);
      }
      if (reporting) {
        presenceApi
          .releaseFocus(clientId)
          .catch(reportFailure("release focus"));
      }
    };
  }, [enabled]);
}
