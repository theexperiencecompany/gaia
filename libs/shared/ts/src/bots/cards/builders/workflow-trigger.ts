import { describeCron } from "../../../utils/cron";
import { getTriggerLabel } from "../../../utils/formatters";
import { formatIntegrationLabel } from "../../../workflows/triggers";

/** What starts a workflow, as a draft or a created workflow carries it. */
interface WorkflowTrigger {
  type: string;
  cronExpression?: string | null;
  /** The integration trigger's slug, e.g. GMAIL_NEW_GMAIL_MESSAGE. */
  slug?: string | null;
}

/** A schedule in words, or the expression itself as code when it has no wording. */
function scheduleLabel(cron: string): string {
  // Unworded, it is the raw expression, whose `*`s would read as emphasis.
  return describeCron(cron) ?? `\`${cron}\``;
}

/**
 * The trigger as the web card's chip reads, as CommonMark: the schedule in
 * words, the integration event by name, or the trigger type.
 */
export function workflowTriggerLabel(trigger: WorkflowTrigger): string {
  if (trigger.cronExpression) return scheduleLabel(trigger.cronExpression);
  if (trigger.slug) return formatIntegrationLabel(trigger.slug.toLowerCase());
  return getTriggerLabel(trigger.type);
}
