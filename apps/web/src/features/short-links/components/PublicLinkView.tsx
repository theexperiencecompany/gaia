import { StandalonePage } from "@/components/layout/StandalonePage";
import { StandaloneBriefing } from "@/features/briefing";
import type { PublicShortLinkView } from "@/types/features/shortLinkTypes";

import { PrintOpenUIArtifactView } from "./PrintOpenUIArtifactView";
import {
  ArtifactPdfDownload,
  PublicOpenUIArtifactView,
} from "./PublicOpenUIArtifactView";
import { PublicSessionArtifactView } from "./PublicSessionArtifactView";
import { PublicTodoDeliverableView } from "./PublicTodoDeliverableView";
import { PublicWorkflowRunView } from "./PublicWorkflowRunView";

interface PublicLinkViewProps {
  slug: string;
  view: PublicShortLinkView;
  /** The paper copy for the PDF export; only artifacts have one. */
  print?: boolean;
}

/** Renders whichever artifact a heygaia.link points at, by its target type. */
export function PublicLinkView({
  slug,
  view,
  print = false,
}: PublicLinkViewProps) {
  if (view.target_type === "briefing") {
    return <StandaloneBriefing briefing={view} />;
  }
  if (view.target_type === "openui_artifact") {
    if (print) return <PrintOpenUIArtifactView view={view} />;
    return (
      <StandalonePage
        width="wide"
        actions={<ArtifactPdfDownload slug={slug} />}
      >
        <PublicOpenUIArtifactView view={view} />
      </StandalonePage>
    );
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
