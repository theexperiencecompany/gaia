import type { ComponentType } from "react";

import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

import { PublicBriefingView } from "./components/PublicBriefingView";
import {
  ArtifactPdfDownload,
  PublicOpenUIArtifactView,
} from "./components/PublicOpenUIArtifactView";
import { PublicSessionArtifactView } from "./components/PublicSessionArtifactView";
import { PublicTodoDeliverableView } from "./components/PublicTodoDeliverableView";
import { PublicWorkflowRunView } from "./components/PublicWorkflowRunView";
import type { LinkViewProps } from "./types";

export interface LinkViewEntry<T extends ShortLinkTargetType> {
  component: ComponentType<LinkViewProps<T>>;
  /** What the link points at, as a noun: "Report this file". */
  label: string;
  width: "reading" | "wide";
  /** Page actions beside Report in the page header. */
  actions?: ComponentType<{ slug: string }>;
  /** The view draws its own bar with Report in it, so the header does not. */
  reportInView?: true;
}

/**
 * How a recipient sees each kind of link. Keyed by every generated target
 * type, so a new type fails type-check until it has a view.
 */
export const LINK_VIEWS: {
  [T in ShortLinkTargetType]: LinkViewEntry<T>;
} = {
  todo_deliverable: {
    component: PublicTodoDeliverableView,
    label: "todo",
    width: "reading",
  },
  briefing: { component: PublicBriefingView, label: "brief", width: "reading" },
  session_artifact: {
    component: PublicSessionArtifactView,
    label: "file",
    width: "reading",
    reportInView: true,
  },
  workflow_run: {
    component: PublicWorkflowRunView,
    label: "workflow run",
    width: "reading",
  },
  openui_artifact: {
    component: PublicOpenUIArtifactView,
    label: "artifact",
    width: "wide",
    actions: ArtifactPdfDownload,
  },
};
