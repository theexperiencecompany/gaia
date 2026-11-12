// heygaia.link public views, generated from the API's `PublicShortLinkView`
// discriminated union (apps/api/app/models/short_link_models.py).

import type {
  PublicBriefing,
  PublicOpenUIArtifact,
  PublicSessionArtifact,
  PublicTodoDeliverable,
  PublicWorkflowRun,
} from "@shared/api/generated";

export type {
  LinkAccess,
  LinkSettings,
  LinkSettingsUpdate,
  PublicBriefing,
  PublicOpenUIArtifact,
  PublicSessionArtifact,
  PublicTodoDeliverable,
  PublicWorkflowRun,
  ShortLinkResponse,
  ShortLinkTargetType,
} from "@shared/api/generated";

export type PublicShortLinkView =
  | PublicTodoDeliverable
  | PublicBriefing
  | PublicSessionArtifact
  | PublicWorkflowRun
  | PublicOpenUIArtifact;
