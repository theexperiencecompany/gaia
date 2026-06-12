export const VOICE_STREAM_TOPIC = "backend-stream-event";

/** LiveKit text-input topic the voice agent listens on for typed user turns. */
export const LK_CHAT_TOPIC = "lk.chat";

/**
 * Event key the voice agent emits right before it speaks a delegated
 * executor's narrated answer. Aligned-transcript segments that start after
 * this marker belong to that narration, which the WebSocket push renders as
 * its own message — the live bubble must not duplicate it.
 * Must match EXECUTOR_SPEAKING_KEY in apps/voice-agent/src/constants.py.
 */
export const EXECUTOR_SPEAKING_KEY = "executor_speaking";
