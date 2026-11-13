import type { WorkflowDraftData } from "../../../chat/types";
import type { Card, CardBlock, CardField } from "../types";
import { workflowTriggerLabel } from "./workflow-trigger";

const DRAFT_TITLE = "Create this workflow?";
const INSTRUCTIONS_CITE = "What it will do";
/** The web card's "Review & Create" button; on a bot, the agent creates it from the reply. */
const CREATE_HINT = "Reply **create** to set it up, or tell me what to change.";

/** The payload as the API streams it; `runs_only_when` is set only for integration triggers. */
type WorkflowDraftPayload = WorkflowDraftData & {
  runs_only_when?: string | null;
};

function draftFields(draft: WorkflowDraftPayload): CardField[] {
  const fields: CardField[] = [
    { label: "Name", value: draft.suggested_title },
    {
      label: "Trigger",
      value: workflowTriggerLabel({
        type: draft.trigger_type,
        cronExpression: draft.cron_expression,
        slug: draft.trigger_slug,
      }),
    },
  ];
  if (draft.runs_only_when) {
    fields.push({ label: "Runs only when", value: draft.runs_only_when });
  }
  return fields;
}

/** A workflow the agent proposed: what it is, what starts it, and what it will do. */
export function buildWorkflowDraftCards(draft: WorkflowDraftPayload): Card[] {
  const blocks: CardBlock[] = [];
  if (draft.suggested_description) {
    blocks.push({ kind: "text", markdown: draft.suggested_description });
  }
  blocks.push({ kind: "fields", fields: draftFields(draft) });
  if (draft.prompt) {
    blocks.push({
      kind: "quote",
      markdown: draft.prompt,
      collapsible: true,
      cite: INSTRUCTIONS_CITE,
    });
  }
  return [
    {
      title: DRAFT_TITLE,
      accent: "warning",
      blocks,
      actions: [],
      textHint: CREATE_HINT,
    },
  ];
}
