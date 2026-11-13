import { parseApprovalDecidedEvent } from "@shared/utils";
import { useCallback, useEffect } from "react";
import { useApprovalSettlementStore } from "@/features/chat/stores/approvalSettlementStore";
import { wsManager } from "@/lib/websocket/WebSocketManager";

/**
 * Subscribe to `hil_approval_decided` and settle the matching card wherever it shows.
 *
 * Without this, a card decided anywhere but the open tab — another device, the
 * review sheet on a different message, an agent-side revoke — stays actionable
 * until the log's decision arrives, and a revoke, which the log never carries,
 * would never show its tombstone.
 */
export function useApprovalDecisionWebSocket() {
  const handleDecided = useCallback((raw: unknown) => {
    const event = parseApprovalDecidedEvent(raw);
    if (!event) return;
    const { approval_id, status, feedback } = event;
    useApprovalSettlementStore
      .getState()
      .settle({ approval_id, status, feedback });
  }, []);

  useEffect(() => {
    wsManager.on("hil_approval_decided", handleDecided);
    return () => {
      wsManager.off("hil_approval_decided", handleDecided);
    };
  }, [handleDecided]);
}
