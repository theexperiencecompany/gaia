import type { IntegrationRef, Workflow } from "@/types/features/workflowTypes";

function getRelativeTime(nextRun: Date, now: Date): string {
  const diffMs = nextRun.getTime() - now.getTime();
  const totalMinutes = Math.floor(diffMs / (1000 * 60));
  const totalHours = Math.floor(totalMinutes / 60);
  const totalDays = Math.floor(totalHours / 24);

  const remHours = totalHours % 24;
  const remMinutes = totalMinutes % 60;

  if (totalDays > 0) {
    return remHours > 0 ? `in ${totalDays}d ${remHours}h` : `in ${totalDays}d`;
  } else if (totalHours > 0) {
    return remMinutes > 0
      ? `in ${totalHours}h ${remMinutes}m`
      : `in ${totalHours}h`;
  } else if (totalMinutes > 0) {
    return `in ${totalMinutes}m`;
  } else {
    return "soon";
  }
}

export function getNextRunDisplay(workflow: Workflow): string | null {
  const { trigger_config } = workflow;
  if (trigger_config.type === "schedule" && trigger_config.next_run) {
    const nextRunValue = trigger_config.next_run as string;
    const nextRun = new Date(nextRunValue);
    const now = new Date();
    if (nextRun > now) {
      return getRelativeTime(nextRun, now);
    }
  }
  return null;
}

export function missingIntegrationsMessage(
  missingIntegrations: IntegrationRef[],
): string {
  const names = missingIntegrations.map((i) => i.name).join(", ");
  return `Connect ${names} to enable this workflow.`;
}
