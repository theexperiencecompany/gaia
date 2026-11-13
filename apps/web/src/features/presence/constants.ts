/** How often an app in view tells the API so; the API's presence window is two of these plus slack. */
export const FOCUS_HEARTBEAT_INTERVAL_MS = 60_000;

/** An unattended focused window is not presence: the keyboard or pointer was used this recently. */
export const FOCUS_INPUT_IDLE_MS = 2 * 60_000;

/** What counts as the user being at the machine. */
export const FOCUS_INPUT_EVENTS = [
  "keydown",
  "pointerdown",
  "pointermove",
  "wheel",
  "touchstart",
] as const;
