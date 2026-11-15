/**
 * The startup list of conversations to follow again, asked until the API answers:
 * a bot often boots before the API it resumes from is listening.
 */
import type { ActiveBotConversation } from "../../api/generated";
import {
  classifyBotFailure,
  isTransientBotFailure,
  recordBotFailure,
} from "../utils/failure-reasons";
import { sanitizeErrorForLog } from "../utils/logger";
import { wideLog } from "../utils/wide-events";

export const RESUME_LIST_RETRY_BASE_MS = 1_000;
export const RESUME_LIST_RETRY_MAX_MS = 30_000;

/** Resolves after ms, or at once when signal aborts. */
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    function done(): void {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}

/**
 * Lists the platform's active conversations, retrying with capped backoff while the
 * failure is one a retry can get past. Null when it refused for good or signal aborted.
 * Logs the 1st, 2nd, 4th, 8th… retry, so an API down for hours costs a few lines.
 */
export async function listActiveUntilAnswered(
  list: () => Promise<ActiveBotConversation[]>,
  signal: AbortSignal,
): Promise<ActiveBotConversation[] | null> {
  for (let attempt = 1; !signal.aborted; attempt += 1) {
    try {
      const active = await list();
      wideLog.set({ list_attempts: attempt });
      return active;
    } catch (error) {
      if (!isTransientBotFailure(classifyBotFailure(error))) {
        recordBotFailure("conversation_resume_list_failed", error, {
          attempts: attempt,
        });
        return null;
      }
      const waitMs = Math.min(
        RESUME_LIST_RETRY_BASE_MS * 2 ** (attempt - 1),
        RESUME_LIST_RETRY_MAX_MS,
      );
      if ((attempt & (attempt - 1)) === 0) {
        wideLog.warning("conversation_resume_list_retrying", {
          ...sanitizeErrorForLog(error),
          attempt,
          wait_ms: waitMs,
        });
      }
      await wait(waitMs, signal);
    }
  }
  return null;
}
