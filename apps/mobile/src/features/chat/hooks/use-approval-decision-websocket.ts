import { useApprovalSettlementStore } from "@gaia/shared/conversation/live";
import { parseApprovalDecidedEvent } from "@gaia/shared/utils";
import { useEffect } from "react";
import { wsManager } from "@/lib/websocket-client";

/**
 * Subscribe to `hil_approval_decided` and settle the matching card wherever it shows,
 * mirroring web: a card decided elsewhere flips in place before the log's decision
 * arrives, and a revoke, which the log never carries, shows its tombstone.
 */
export function useApprovalDecisionWebSocket(): void {
  useEffect(() => {
    const handleDecided = (raw: unknown): void => {
      const event = parseApprovalDecidedEvent(raw);
      if (!event) return;
      const { approval_id, status, feedback } = event;
      useApprovalSettlementStore
        .getState()
        .settle({ approval_id, status, feedback });
    };
    return wsManager.subscribe("hil_approval_decided", handleDecided);
  }, []);
}
