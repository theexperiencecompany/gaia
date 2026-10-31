import type { TodoRunWake } from "../api/generated";
import { getTriggerDisplayInfoBySlug } from "../workflows/triggerDisplay";

/** Words for one watched event, from the trigger display registry; its id when it has none. */
function eventLabel(triggerName: string): string {
  return (
    getTriggerDisplayInfoBySlug(triggerName, {
      type: "integration",
      trigger_name: triggerName,
    })?.label ?? `on ${triggerName}`
  );
}

/** Say what woke a tracked todo's run, for the user's side of its chat. */
export function describeTodoRunWake(wake: TodoRunWake): string {
  switch (wake.kind) {
    case "schedule":
      return "Scheduled run";
    case "trigger":
      return `Woke up ${wake.trigger_names.map(eventLabel).join(" and ")}`;
    case "approval":
      return wake.approval_summary
        ? `You approved: ${wake.approval_summary}`
        : "You approved it";
  }
}
