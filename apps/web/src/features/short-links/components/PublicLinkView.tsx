import { StandalonePage } from "@/components/layout/StandalonePage";
import type {
  LinkContent,
  LinkEnvelope,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

import { LINK_VIEWS } from "../registry";
import type { LinkViewOf } from "../types";
import { ReportLinkButton } from "./ReportLinkButton";
import { ShareLinkControls } from "./ShareLinkControls";

function LinkPage<T extends ShortLinkTargetType>({
  slug,
  targetType,
  view,
  content,
  downloadable,
  ownerTargetId,
}: {
  slug: string;
  targetType: T;
  view: LinkViewOf<T>;
  content: LinkContent | null;
  downloadable: boolean;
  /** Set only when the viewer owns the link: the target its share settings act on. */
  ownerTargetId: string | null;
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
          {ownerTargetId && (
            <ShareLinkControls
              targetType={targetType}
              targetId={ownerTargetId}
            />
          )}
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
      ownerTargetId={envelope.is_owner ? envelope.owner_target_id : null}
    />
  );
}
