import type { TodoRunWake } from "../api/generated";

/** Words for one watched event, given its trigger id. */
export type TriggerEventLabel = (triggerName: string) => string;

const triggerIdLabel: TriggerEventLabel = (triggerName) => `on ${triggerName}`;

/**
 * Say what woke a tracked todo's run, for the user's side of its chat.
 * Apps with a trigger display registry pass `eventLabel` to word the events.
 */
export function describeTodoRunWake(
  wake: TodoRunWake,
  eventLabel: TriggerEventLabel = triggerIdLabel,
): string {
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
