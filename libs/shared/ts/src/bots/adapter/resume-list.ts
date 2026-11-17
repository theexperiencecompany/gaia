/**
 * The startup list of conversations to follow again: a bot often boots before the API it
 * resumes from is listening, so the list is asked under the OWN_API retry policy.
 */
import type { ActiveBotConversation } from "../../api/generated";
import { RETRY_POLICY, withRetry } from "../../retry";
import {
  classifyBotFailure,
  isTransientBotFailure,
  recordBotFailure,
} from "../utils/failure-reasons";
import { sanitizeErrorForLog } from "../utils/logger";
import { wideLog } from "../utils/wide-events";

/**
 * Lists the platform's active conversations, retrying a failure a retry can get past. Null,
 * with the failure recorded, when it refused for good, the retries ran out, or signal aborted.
 */
export async function listActiveUntilAnswered(
  list: () => Promise<ActiveBotConversation[]>,
  signal: AbortSignal,
): Promise<ActiveBotConversation[] | null> {
  let attempts = 1;
  try {
    const active = await withRetry(RETRY_POLICY.OWN_API, list, {
      transient: (error) => isTransientBotFailure(classifyBotFailure(error)),
      onRetry: (error, attempt) => {
        attempts = attempt + 1;
        wideLog.warning("conversation_resume_list_retrying", {
          ...sanitizeErrorForLog(error),
          attempt,
        });
      },
      signal,
    });
    wideLog.set({ list_attempts: attempts });
    return active;
  } catch (error) {
    if (signal.aborted) return null;
    recordBotFailure("conversation_resume_list_failed", error, { attempts });
    return null;
  }
}
