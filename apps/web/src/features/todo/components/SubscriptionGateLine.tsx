"use client";

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { useSubscriptionGate } from "@/features/todo/hooks/useSubscriptionGate";
import { RunsOnlyWhenPanel } from "@/features/workflows/triggers/components/RunsOnlyWhenPanel";
import { gateAuthorLine } from "@/features/workflows/utils/gateEdit";

interface SubscriptionGateLineProps {
  todoId: string;
  subscriptionId: string;
  gate: AuthoredGateView | SystemGateView;
}

/** A tracked todo's "Runs only when" panel for one gated run watch. */
export function SubscriptionGateLine({
  todoId,
  subscriptionId,
  gate,
}: SubscriptionGateLineProps) {
  const { saveCondition, setEnabled } = useSubscriptionGate(
    todoId,
    subscriptionId,
    gate,
  );

  return (
    <RunsOnlyWhenPanel
      condition={gate.display_condition}
      enabled={gate.enabled}
      author={gateAuthorLine(gate)}
      enforced={gate.enforced}
      recentSkips={gate.recent_skips}
      editable={gate.kind === "authored"}
      onConditionSave={saveCondition}
      onEnabledChange={setEnabled}
    />
  );
}
