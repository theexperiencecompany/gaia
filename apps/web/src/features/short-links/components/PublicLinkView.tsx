import { StandalonePage } from "@/components/layout/StandalonePage";
import { StandaloneBriefing } from "@/features/briefing";
import type { PublicShortLinkView } from "@/types/features/shortLinkTypes";

import { PublicSessionArtifactView } from "./PublicSessionArtifactView";
import { PublicTodoDeliverableView } from "./PublicTodoDeliverableView";
import { PublicWorkflowRunView } from "./PublicWorkflowRunView";

interface PublicLinkViewProps {
  slug: string;
  view: PublicShortLinkView;
}

/** Renders whichever artifact a heygaia.link points at, by its target type. */
export function PublicLinkView({ slug, view }: PublicLinkViewProps) {
  if (view.target_type === "briefing") {
    return <StandaloneBriefing briefing={view} />;
  }
  return (
    <StandalonePage>
      {view.target_type === "todo_deliverable" && (
        <PublicTodoDeliverableView view={view} />
      )}
      {view.target_type === "session_artifact" && (
        <PublicSessionArtifactView slug={slug} view={view} />
      )}
      {view.target_type === "workflow_run" && (
        <PublicWorkflowRunView view={view} />
      )}
    </StandalonePage>
  );
}
