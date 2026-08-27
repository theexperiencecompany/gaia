import { useParams } from "next/navigation";
import { useCallback } from "react";
import { turnManager } from "@/features/chat/stream/turnManager";
import { useStreamStore } from "@/stores/streamStore";

/**
 * Swap "Waiting for your approval" for a resuming state the moment the user
 * decides — the resolved frame arrives on the resumed run's stream, which can
 * take seconds; the indicator must not keep asking for an answer it has.
 *
 * Scoped to the conversation the card belongs to. A second conversation paused
 * on its own gate must keep asking: deciding this one says nothing about that
 * one. The key comes from `turnManager.resolveKey` rather than the route id
 * alone, so a not-yet-saved new chat — whose session is keyed by a pending id
 * whilst the route is still /c — resolves the same way the streaming layer
 * keys it.
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
