// heygaia.link public views. Mirrors the backend `PublicShortLinkView`
// discriminated union in `apps/api/app/models/short_link_models.py` — the only
// shapes the public resolver ever returns.

import type { WorkflowExecution } from "@/features/workflows/types/workflowExecutionTypes";
import type { BriefingPayload } from "@/types/features/briefingTypes";

export type ShortLinkTargetType =
  | "todo_deliverable"
  | "briefing"
  | "session_artifact"
  | "workflow_run";

export interface PublicTodoDeliverable {
  target_type: "todo_deliverable";
  title: string;
  completed: boolean;
  content: string;
}

export interface PublicBriefing extends Omit<BriefingPayload, "sections"> {
  target_type: "briefing";
  kind: "daily" | "weekly";
  sections: {
    numeral: string;
    title: string;
    items: { text: string; kind: string }[];
  }[];
}

export interface PublicSessionArtifact {
  target_type: "session_artifact";
  filename: string;
  content_type: string;
  size_bytes: number;
  /** Text of a text file; null for binary files, which load from the file route. */
  content: string | null;
}

export interface PublicWorkflowRun {
  target_type: "workflow_run";
  workflow_title: string;
  status: WorkflowExecution["status"];
  started_at: string;
  completed_at: string | null;
  summary: string;
}

export type PublicShortLinkView =
  | PublicTodoDeliverable
  | PublicBriefing
  | PublicSessionArtifact
  | PublicWorkflowRun;
