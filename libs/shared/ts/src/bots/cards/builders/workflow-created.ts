import type { WorkflowCreatedData } from "../../../chat/types";
import type { Card, CardBlock } from "../types";
import { workflowTriggerLabel } from "./workflow-trigger";

const CREATED_TITLE = "Workflow created";
const INACTIVE_FOOTER = "Not active";

/** The receipt for a workflow the agent created without a draft. */
export function buildWorkflowCreatedCards(
  workflow: WorkflowCreatedData,
): Card[] {
  const blocks: CardBlock[] = [];
  if (workflow.description) {
    blocks.push({ kind: "text", markdown: workflow.description });
  }
  blocks.push({
    kind: "fields",
    fields: [
      { label: "Name", value: workflow.title },
      {
        label: "Trigger",
        value: workflowTriggerLabel({
          type: workflow.trigger_config.type,
          cronExpression: workflow.trigger_config.cron_expression,
          slug: workflow.trigger_config.trigger_name,
        }),
      },
    ],
  });
  return [
    {
      title: CREATED_TITLE,
      accent: "brand",
      blocks,
      actions: [],
      footer: workflow.activated ? undefined : INACTIVE_FOOTER,
    },
  ];
}
