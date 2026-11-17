/**
 * The startup list of conversations to follow again: a bot often boots before the API it
 * resumes from is listening, so the list is asked under UNTIL_IT_LANDS until the API answers.
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
 * Lists the platform's active conversations, retrying every transient failure on a capped
 * backoff. Null, with the failure recorded, when the API refused for good; null on shutdown.
 * Logs the 1st, 2nd, 4th, 8th… retry, so an API down for hours costs a few lines.
 */
export async function listActiveUntilAnswered(
  list: () => Promise<ActiveBotConversation[]>,
  signal: AbortSignal,
): Promise<ActiveBotConversation[] | null> {
  let attempts = 1;
  try {
    const active = await withRetry(RETRY_POLICY.UNTIL_IT_LANDS, list, {
      transient: (error) => isTransientBotFailure(classifyBotFailure(error)),
      onRetry: (error, attempt) => {
        attempts = attempt + 1;
        if ((attempt & (attempt - 1)) !== 0) return;
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
