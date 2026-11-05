import type {
  AuthoredGateView,
  GateEdit,
  SystemGateView,
} from "@shared/api/generated";
import { useState } from "react";
import { editSubscriptionGate } from "@/features/todo/api/todoApi";
import { useTodoStore } from "@/stores/todoStore";

/**
 * One run watch's gate as the sidebar edits it: the condition commits when the
 * user leaves the field, and the switch saves at once with enabled alone.
 */
export function useSubscriptionGate(
  todoId: string,
  subscriptionId: string,
  gate: AuthoredGateView | SystemGateView,
) {
  const updateTodoOptimistic = useTodoStore(
    (state) => state.updateTodoOptimistic,
  );
  const [condition, setCondition] = useState(gate.display_condition);

  const save = async (edit: GateEdit) => {
    try {
      const todo = await editSubscriptionGate(todoId, subscriptionId, edit);
      updateTodoOptimistic(todoId, todo);
    } catch {
      // The API layer already told the user; the field goes back to what is stored.
      setCondition(gate.display_condition);
    }
  };

  const commitCondition = () => {
    const edited = condition.trim();
    if (!edited || edited === gate.display_condition) {
      setCondition(gate.display_condition);
      return;
    }
    void save({ condition: edited, enabled: gate.enabled });
  };

  return {
    condition,
    setCondition,
    commitCondition,
    setEnabled: (enabled: boolean) => void save({ enabled }),
  };
}
