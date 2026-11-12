import { StandalonePage } from "@/components/layout/StandalonePage";
import type {
  LinkContent,
  LinkEnvelope,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

import { LINK_VIEWS } from "../registry";
import type { LinkViewOf } from "../types";
import { ReportLinkButton } from "./ReportLinkButton";

function LinkPage<T extends ShortLinkTargetType>({
  slug,
  targetType,
  view,
  content,
  downloadable,
}: {
  slug: string;
  targetType: T;
  view: LinkViewOf<T>;
  content: LinkContent | null;
  downloadable: boolean;
}) {
  const entry = LINK_VIEWS[targetType];
  const View = entry.component;
  const Actions = entry.actions;
  const reportAction = <ReportLinkButton slug={slug} label={entry.label} />;
  return (
    <StandalonePage
      width={entry.width}
      actions={
        <>
          {Actions && <Actions slug={slug} />}
          {!entry.reportInView && reportAction}
        </>
      }
    >
      <View
        slug={slug}
        view={view}
        content={content}
        downloadable={downloadable}
        reportAction={reportAction}
      />
    </StandalonePage>
  );
}

/** Renders whichever artifact a heygaia.link points at, from its entry in LINK_VIEWS. */
export function PublicLinkView({
  slug,
  envelope,
}: {
  slug: string;
  envelope: LinkEnvelope;
}) {
  return (
    <LinkPage
      slug={slug}
      targetType={envelope.view.target_type}
      view={envelope.view}
      content={envelope.content}
      downloadable={envelope.downloadable}
    />
  );
}
