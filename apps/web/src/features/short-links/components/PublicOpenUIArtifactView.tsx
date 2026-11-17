"use client";

import { Download01Icon } from "@icons";
import { LinkButton } from "@/components/shared/LinkButton";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { shortLinkPdfDownloadUrl } from "@/features/short-links/api/shortLinksApi";
import type { PublicOpenUIArtifact } from "@/types/features/shortLinkTypes";

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

/** A shared artifact: who shared it, then its program rendered by the artifact library. */
export function PublicOpenUIArtifactView({
  view,
}: {
  view: PublicOpenUIArtifact;
}) {
  return (
    <div className="space-y-2">
      {view.shared_by ? (
        <p className="text-sm text-zinc-400">Shared by {view.shared_by}</p>
      ) : null}
      <div className="rounded-2xl bg-zinc-900">
        <LazyArtifactRenderer program={view.program} />
      </div>
    </div>
  );
}
