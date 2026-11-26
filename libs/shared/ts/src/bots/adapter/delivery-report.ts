/** Keeps a follower's delivery cursor on the server, where a restarted bot reads it back. */

import { RETRY_POLICY, withRetry } from "../../retry";
import type { GaiaClient } from "../api";
import type { DeliveryReport } from "../conversation/follower.types";
import type { PlatformName } from "../types";
import {
  classifyBotFailure,
  isTransientBotFailure,
} from "../utils/failure-reasons";
import { sanitizeErrorForLog } from "../utils/logger";
import { wideLog } from "../utils/wide-events";

/**
 * Send one report, retrying a transient failure: a report is idempotent, and one lost leaves
 * a placed reaction owed, placed again by the next follow. A write that still fails only
 * means a restart could resend from the last cursor kept, so delivery goes on and the miss
 * is logged. No shutdown signal: a stopping bot's last report is what its successor resumes from.
 */
export async function recordDeliveryReport(
  gaia: GaiaClient,
  platform: PlatformName,
  conversationId: string,
  report: DeliveryReport,
): Promise<void> {
  try {
    await withRetry(
      RETRY_POLICY.OWN_API,
      () => gaia.recordDelivered(conversationId, { platform, ...report }),
      {
        transient: (error) => isTransientBotFailure(classifyBotFailure(error)),
      },
    );
  } catch (error) {
    wideLog.warning("delivery_cursor_not_recorded", {
      ...sanitizeErrorForLog(error),
      conversation_id: conversationId,
      delivered_seq: report.delivered_seq,
    });
  }
}
