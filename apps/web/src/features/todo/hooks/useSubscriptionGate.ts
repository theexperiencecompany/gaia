import type {
  AuthoredGateView,
  GateEdit,
  SystemGateView,
} from "@shared/api/generated";
import { editSubscriptionGate } from "@/features/todo/api/todoApi";
import { useTodoStore } from "@/stores/todoStore";

/** One run watch's gate as the sidebar edits it: a saved rule and the switch each store at once. */
export function useSubscriptionGate(
  todoId: string,
  subscriptionId: string,
  gate: AuthoredGateView | SystemGateView,
) {
  const updateTodoOptimistic = useTodoStore(
    (state) => state.updateTodoOptimistic,
  );

  const save = async (edit: GateEdit) => {
    try {
      updateTodoOptimistic(
        todoId,
        await editSubscriptionGate(todoId, subscriptionId, edit),
      );
    } catch {
      // The API layer already told the user; the panel keeps showing what is stored.
    }
  };

  return {
    saveCondition: (condition: string) =>
      void save({ condition, enabled: gate.enabled }),
    setEnabled: (enabled: boolean) => void save({ enabled }),
  };
}
