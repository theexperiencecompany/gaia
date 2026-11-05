"use client";

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { useSubscriptionGate } from "@/features/todo/hooks/useSubscriptionGate";
import { RunsOnlyWhenPanel } from "@/features/workflows/triggers/components/RunsOnlyWhenPanel";

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
      saved={gate}
      editable={gate.kind === "authored"}
      onConditionSave={saveCondition}
      onEnabledChange={setEnabled}
    />
  );
}
