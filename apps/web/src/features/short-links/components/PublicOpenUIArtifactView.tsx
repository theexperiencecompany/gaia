"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Download01Icon } from "@icons";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { shortLinkPdfDownloadUrl } from "@/features/short-links/api/linkViewerApi";
import type { PublicOpenUIArtifact } from "@/types/features/shortLinkTypes";

/** Download the shared artifact as a PDF; sits in the page header. */
export function ArtifactPdfDownload({ slug }: { slug: string }) {
  return (
    <Button
      as={Link}
      href={shortLinkPdfDownloadUrl(slug)}
      size="sm"
      variant="flat"
      startContent={<Download01Icon className="size-4" />}
    >
      Download PDF
    </Button>
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
