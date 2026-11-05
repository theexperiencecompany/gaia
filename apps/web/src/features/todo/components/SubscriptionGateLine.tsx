"use client";

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { useSubscriptionGate } from "@/features/todo/hooks/useSubscriptionGate";
import { RunsOnlyWhenField } from "@/features/workflows/triggers/components/RunsOnlyWhenField";

interface SubscriptionGateLineProps {
  todoId: string;
  subscriptionId: string;
  gate: AuthoredGateView | SystemGateView;
}

/** A tracked todo's "Runs only when" line for one gated run watch. */
export function SubscriptionGateLine({
  todoId,
  subscriptionId,
  gate,
}: SubscriptionGateLineProps) {
  const { condition, setCondition, commitCondition, setEnabled } =
    useSubscriptionGate(todoId, subscriptionId, gate);

  return (
    <RunsOnlyWhenField
      condition={condition}
      enabled={gate.enabled}
      editable={gate.kind === "authored"}
      enforced={gate.enforced}
      onConditionChange={setCondition}
      onConditionBlur={commitCondition}
      onEnabledChange={setEnabled}
    />
  );
}
