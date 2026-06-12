import { useCallback, useEffect } from "react";
import type {
  SubagentGroupData,
  ToolDataEntry,
} from "@/config/registries/toolRegistry";
import { db, type IMessage } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

/**
 * WebSocket payload for an agent-initiated executor cancellation.
 * Emitted by the backend `cancel_executor` tool — the only signal the frontend
 * gets that a cancel it did NOT initiate (i.e. not the Stop button) happened.
 */
interface ExecutorCancelledEvent {
  type: "executor.cancelled";
  conversation_id: string;
  cancelled?: string[];
}

/**
 * Recursively stamp `completed_at` on any subagent group still marked running.
 *
 * A cancelled executor never emits the subagent's end event, so its group
 * persists with `completed_at === null` — which `SubagentRow` reads as "still
 * running" and renders a spinner forever. Returns the same reference when
 * nothing changed so callers can skip a redundant write.
 */
const finalizeGroup = (
  group: SubagentGroupData,
  now: string,
): SubagentGroupData => {
  const nested = group.nested_subagents.map((g) => finalizeGroup(g, now));
  const nestedChanged = nested.some((g, i) => g !== group.nested_subagents[i]);
  if (group.completed_at !== null) {
    return nestedChanged ? { ...group, nested_subagents: nested } : group;
  }
  return { ...group, completed_at: now, nested_subagents: nested };
};

const finalizeToolData = (
  toolData: ToolDataEntry[],
  now: string,
): ToolDataEntry[] | null => {
  let changed = false;
  const next = toolData.map((entry) => {
    if (entry.tool_name !== "subagent_group") return entry;
    const finalized = finalizeGroup(entry.data as SubagentGroupData, now);
    if (finalized === entry.data) return entry;
    changed = true;
    return { ...entry, data: finalized };
  });
  return changed ? next : null;
};

/**
 * Subscribe to `executor.cancelled` and undo the stuck loading UI.
 *
 * When the agent cancels an executor task (e.g. user says "stop that"), the
 * frontend otherwise has no idea: the executor-pending bridge keeps the bottom
 * loading indicator up until its 120s safety timeout, and any in-flight tool
 * card spins forever (its subagent group never got an end event). This clears
 * both at the source.
 */
export function useExecutorCancelWebSocket() {
  const handleCancelled = useCallback(async (raw: unknown) => {
    const event = raw as ExecutorCancelledEvent;
    const { conversation_id } = event;
    if (!conversation_id) return;

    const store = useChatStore.getState();

    // 1. Drop the executor-pending bridge so the bottom loading indicator
    //    clears. The cancelling comms turn resets isLoading/loadingText via its
    //    own completion; this stale pending flag is the only thing left holding
    //    the indicator open.
    if (store.executorPendingConversationId === conversation_id) {
      store.setExecutorPendingConversationId(null);
    }

    // 2. Finalize any in-flight tool cards so they stop spinning — immediately
    //    in the store and durably in IndexedDB (survives refresh). The backend
    //    persists the same finalization to Mongo for other devices.
    const now = new Date().toISOString();
    const messages = store.messagesByConversation[conversation_id] ?? [];
    for (const message of messages) {
      if (!message.tool_data?.length) continue;
      const finalized = finalizeToolData(message.tool_data, now);
      if (!finalized) continue;
      const updated: IMessage = {
        ...message,
        tool_data: finalized,
        updatedAt: new Date(),
      };
      store.addOrUpdateMessage(updated);
      void db.putMessage(updated);
    }
  }, []);

  useEffect(() => {
    wsManager.on("executor.cancelled", handleCancelled);
    return () => {
      wsManager.off("executor.cancelled", handleCancelled);
    };
  }, [handleCancelled]);
}
