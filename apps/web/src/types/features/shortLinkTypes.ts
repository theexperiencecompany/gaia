// heygaia.link types, generated from apps/api/app/models/short_link_models.py.

export type {
  ContentTokenResponse,
  ErrorEnvelope,
  LinkAccess,
  LinkContent,
  LinkDenial,
  LinkEnvelope,
  LinkPreviewMeta,
  LinkSettings,
  LinkSettingsUpdate,
  PublicOpenUIArtifact,
  PublicTodoDeliverable,
  PublicWorkflowRun,
  PublicWorkspaceFile,
  ReportReason,
  ShortLinkResponse,
  ShortLinkTargetType,
} from "@shared/api/generated";

import type { ShortLinkTargetRequest } from "@shared/api/generated";

/** One of the owner's things a link points at: a record by id, or a workspace file by conversation and path. */
export type LinkTarget = ShortLinkTargetRequest["target"];
