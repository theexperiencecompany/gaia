import { Chip } from "@heroui/react";
import { CheckmarkCircle02Icon, Clock01Icon, FlashIcon } from "@icons";
import type { TodoRunWake } from "@shared/api/generated";
import { describeTodoRunWake } from "@shared/todos";

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
    <Chip variant="secondary" className="mx-3 mt-2 mb-1">
      <Icon width={16} height={16} className="mx-1" />
      <Chip.Label>{describeTodoRunWake(wake)}</Chip.Label>
    </Chip>
  );
}
