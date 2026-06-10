/** Pre-defined acknowledgment sound played when the popup activates. */
export const WAKE_ACK_AUDIO_SRC = "/audio/wake-ack.m4a";

/** House easing — snappy deceleration (see DESIGN.md). */
export const POPUP_EASE: [number, number, number, number] = [0.19, 1, 0.22, 1];

/** Popup panel entrance/exit duration, in seconds. */
export const POPUP_TRANSITION_SECONDS = 0.25;

/** Hint copy shown under the orb per agent state. */
export const AGENT_STATE_HINTS = {
  idle: "Say “Hey GAIA”",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking…",
} as const;
