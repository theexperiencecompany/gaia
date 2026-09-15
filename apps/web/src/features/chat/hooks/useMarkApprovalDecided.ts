import { useParams } from "next/navigation";
import { useCallback } from "react";
import { turnManager } from "@/features/chat/stream/turnManager";
import { useStreamStore } from "@/stores/streamStore";

/**
 * Swap "Waiting for your approval" for a resuming state the moment the user
 * decides, since the resolved frame can take seconds to arrive on the stream.
 *
 * Scoped via `turnManager.resolveKey` (not the route id alone) so an
 * unsaved new chat, keyed by a pending id, resolves the same way the stream does.
 */
export function useMarkApprovalDecided(): () => void {
  const { id } = useParams<{ id?: string }>();
  const clearAwaitingApproval = useStreamStore(
    (state) => state.clearAwaitingApproval,
  );
  return useCallback(
    () => clearAwaitingApproval(turnManager.resolveKey(id ?? null)),
    [clearAwaitingApproval, id],
  );
}
