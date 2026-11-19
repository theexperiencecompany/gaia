// heygaia.link public views, generated from the API's `PublicShortLinkView`
// discriminated union (apps/api/app/models/short_link_models.py).

import type {
  PublicBriefing,
  PublicSessionArtifact,
  PublicTodoDeliverable,
  PublicWorkflowRun,
} from "@shared/api/generated";

export type {
  PublicBriefing,
  PublicSessionArtifact,
  PublicTodoDeliverable,
  PublicWorkflowRun,
  ShortLinkTargetType,
} from "@shared/api/generated";

export type PublicShortLinkView =
  | PublicTodoDeliverable
  | PublicBriefing
  | PublicSessionArtifact
  | PublicWorkflowRun;
