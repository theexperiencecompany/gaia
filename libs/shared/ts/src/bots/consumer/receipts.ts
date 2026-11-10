/**
 * Delivery receipt a bot publishes to the receipts queue once it has settled an
 * outbound envelope that carries an `outbox_message_id`. Mirrors
 * ``OutboundReceipt`` in ``apps/api/app/schemas/outbound.py``.
 *
 * One receipt per envelope part: the platform message ids of every bubble sent,
 * and how the part ended. A part with no receipt is unknown, not failed.
 */

import type { PlatformName } from "../types";

export const RECEIPT_STATUS = {
  /** Every bubble of the part went out. */
  SENT: "sent",
  /** A send was attempted and failed for good. */
  FAILED: "failed",
  /** The envelope was rejected before any send. */
  DEAD_LETTERED: "dead_lettered",
} as const;

export type ReceiptStatus =
  (typeof RECEIPT_STATUS)[keyof typeof RECEIPT_STATUS];

export interface OutboundReceipt {
  envelope_id: string;
  outbox_message_id: string;
  part_index: number;
  platform: PlatformName;
  /** Ids of the platform messages sent for this part, in order; empty when none went out. */
  platform_message_ids: string[];
  status: ReceiptStatus;
  /** The failure reason code; null when sent. */
  error: string | null;
  /** ISO-8601 time the part settled. */
  occurred_at: string;
}
