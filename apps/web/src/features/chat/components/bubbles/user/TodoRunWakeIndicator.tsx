import { Chip } from "@heroui/chip";
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
    <Chip
      variant="flat"
      radius="lg"
      className="mx-3 mt-2 mb-1"
      startContent={<Icon width={16} height={16} className="mx-1" />}
    >
      {describeTodoRunWake(wake)}
    </Chip>
  );
}
