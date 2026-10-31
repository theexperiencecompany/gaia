import { CheckmarkCircle02Icon, Clock01Icon, FlashIcon } from "@icons";
import type { TodoRunWake } from "@shared/api/generated";
import { describeTodoRunWake } from "@shared/todos";
import { triggerEventLabel } from "@/features/todo/utils/todoRunWake";

interface TodoRunWakeIndicatorProps {
  wake: TodoRunWake;
}

const WAKE_ICONS = {
  schedule: Clock01Icon,
  trigger: FlashIcon,
  approval: CheckmarkCircle02Icon,
} satisfies Record<TodoRunWake["kind"], typeof Clock01Icon>;

/** The user's side of a tracked todo's run: what woke it, as a workflow run shows its card. */
export function TodoRunWakeIndicator({ wake }: TodoRunWakeIndicatorProps) {
  const Icon = WAKE_ICONS[wake.kind];
  return (
    <div className="mx-3 mt-2 mb-1 flex w-fit items-center gap-2 rounded-xl bg-zinc-700 px-2 py-1">
      <Icon size={17} className="text-zinc-300" />
      <span className="text-sm font-light text-zinc-200">
        {describeTodoRunWake(wake, triggerEventLabel)}
      </span>
    </div>
  );
}
