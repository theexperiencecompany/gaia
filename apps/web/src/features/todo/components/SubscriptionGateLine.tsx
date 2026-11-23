"use client";

import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { useSubscriptionGate } from "@/features/todo/hooks/useSubscriptionGate";
import { MAIL_TRIGGER_NAMES } from "@/features/workflows/constants/gates";
import { GateRow } from "@/features/workflows/triggers/components/GateRow";

interface SubscriptionGateLineProps {
  todoId: string;
  subscriptionId: string;
  triggerName: string;
  gate: AuthoredGateView | SystemGateView;
}

/** A tracked todo's rule row for one gated run watch. */
export function SubscriptionGateLine({
  todoId,
  subscriptionId,
  triggerName,
  gate,
}: SubscriptionGateLineProps) {
  const { saveCondition, setEnabled } = useSubscriptionGate(
    todoId,
    subscriptionId,
    gate,
  );

  return (
    <GateRow
      condition={gate.display_condition}
      enabled={gate.enabled}
      saved={gate}
      editable={gate.kind === "authored"}
      watchesMail={MAIL_TRIGGER_NAMES.has(triggerName)}
      onConditionSave={saveCondition}
      onEnabledChange={setEnabled}
    />
  );
}
