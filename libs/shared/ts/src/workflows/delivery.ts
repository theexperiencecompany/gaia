import type { WorkflowDelivery } from "../api/generated";

/** Every delivery mode, in the order the workflow modal offers them. */
export const WORKFLOW_DELIVERIES = [
  "now",
  "brief",
  "silent",
] as const satisfies readonly WorkflowDelivery[];

/**
 * Delivery for a workflow added in one click from a card (a use case, a
 * suggestion), where there is no form to choose in: the user just asked for it,
 * so they hear about it. They can change it from the workflow afterwards.
 */
export const ONE_CLICK_WORKFLOW_DELIVERY: WorkflowDelivery = "now";

export const WORKFLOW_DELIVERY_COPY: Record<
  WorkflowDelivery,
  { label: string; description: string }
> = {
  now: {
    label: "Tell me now",
    description: "GAIA messages you with the result as soon as each run ends.",
  },
  brief: {
    label: "Add to my brief",
    description: "Results wait for your next daily brief.",
  },
  silent: {
    label: "Don't notify me",
    description: "Results stay in the workflow. You only hear about failures.",
  },
};
