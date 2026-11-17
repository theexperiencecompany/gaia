"use client";

import { Download01Icon } from "@icons";
import { LinkButton } from "@/components/shared/LinkButton";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { shortLinkPdfDownloadUrl } from "@/features/short-links/api/linkViewerApi";
import type { PublicOpenUIArtifact } from "@/types/features/shortLinkTypes";

import { useReaderDateLabel } from "../hooks/useReaderDateLabel";

/** Download the shared artifact as a PDF; sits in the page header. */
export function ArtifactPdfDownload({ slug }: { slug: string }) {
  return (
    <LinkButton
      href={shortLinkPdfDownloadUrl(slug)}
      size="sm"
      variant="default-soft"
    >
      <Download01Icon className="size-4" />
      Download PDF
    </LinkButton>
  );
}

/** A shared artifact: who shared it and when, then its program rendered by the artifact library. */
export function PublicOpenUIArtifactView({
  view,
}: {
  view: PublicOpenUIArtifact;
}) {
  const createdLabel = useReaderDateLabel(view.created_at);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm text-zinc-400">
        {view.shared_by ? <p>Shared by {view.shared_by}</p> : null}
        <time dateTime={view.created_at} className="text-xs text-zinc-500">
          {createdLabel}
        </time>
      </div>
      <div className="rounded-2xl bg-zinc-900">
        <LazyArtifactRenderer program={view.program} />
      </div>
    </div>
  );
}
