/**
 * Reports a message a user should have received and did not. The API groups the
 * reports into Slack incidents (`POST /api/v1/bot/delivery-failures`).
 *
 * Reporting never throws into the delivery path it is called from: a report that
 * cannot be sent is logged at error level with what finds the lost message.
 */
import type {
  DeliveryFailureKind,
  DeliveryFailureReport,
} from "../api/generated";
import type { GaiaClient } from "./api";
import type { PlatformName } from "./types";
import {
  BOT_FAILURE_REASON,
  type BotFailureReason,
} from "./utils/failure-reasons";
import { createBotLogger, sanitizeErrorForLog } from "./utils/logger";

/** The kinds a bot reports; the API adds `enqueue_failed` and `expired` itself. */
export const DELIVERY_FAILURE_KIND = {
  PLATFORM_REJECTED: "platform_rejected",
  SEND_FAILED: "send_failed",
  ENVELOPE_REJECTED: "envelope_rejected",
  REPLY_FAILED: "reply_failed",
} as const satisfies Record<string, DeliveryFailureKind>;

/** What a call site knows about a lost message; the reporter adds platform and time. */
export type DeliveryFailure = Omit<
  DeliveryFailureReport,
  "platform" | "occurred_at"
>;

/** Fire-and-forget: sends the report in the background and returns at once. */
export type ReportDeliveryFailure = (failure: DeliveryFailure) => void;

/**
 * Refusals the user gets a prompt for (link your account, upgrade). They are the
 * product working, not a reply that failed, so they never alert.
 */
const EXPECTED_REFUSALS: ReadonlySet<BotFailureReason> = new Set([
  BOT_FAILURE_REASON.ACCOUNT_NOT_LINKED,
  BOT_FAILURE_REASON.PLAN_REQUIRED,
]);

/** Matches the API's limit on `error_message`. */
const ERROR_MESSAGE_MAX_LENGTH = 500;
const URL_PATTERN = /https?:\/\/\S+/g;

/**
 * A thrown error as alert text, after an optional `context` prefix: its HTTP status
 * and message, with URLs removed (Telegram's carry the bot token in the path) and
 * capped at the API's limit.
 */
export function describeErrorForAlert(
  error: unknown,
  context?: string,
): string {
  const { error: message, http_status: status } = sanitizeErrorForLog(error);
  const text = String(message ?? "").replace(URL_PATTERN, "<url>");
  const described = status === undefined ? text : `HTTP ${status}: ${text}`;
  const prefixed = context ? `${context}: ${described}` : described;
  return prefixed.slice(0, ERROR_MESSAGE_MAX_LENGTH);
}

/** Whether a failed chat turn or command, classified as `reason`, is a lost reply. */
export function isLostReply(reason: BotFailureReason): boolean {
  return !EXPECTED_REFUSALS.has(reason);
}

export function createDeliveryFailureReporter(
  gaia: GaiaClient,
  platform: PlatformName,
): ReportDeliveryFailure {
  const logger = createBotLogger(platform, "delivery-failures");
  return (failure) => {
    const report: DeliveryFailureReport = {
      ...failure,
      platform,
      occurred_at: new Date().toISOString(),
    };
    // An async wrapper, not a bare .catch(): a synchronous throw from the client
    // must become a logged rejection too, never an exception in the caller.
    const send = async (): Promise<void> => {
      await gaia.reportDeliveryFailure(report);
    };
    send().catch((error: unknown) => {
      logger.error(
        "delivery_failure_report_failed",
        {
          kind: failure.kind,
          reason: failure.reason,
          error_code: failure.error_code,
          envelope_id: failure.envelope_id,
        },
        error,
      );
    });
  };
}
