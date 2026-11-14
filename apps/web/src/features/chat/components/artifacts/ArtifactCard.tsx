"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Alert01Icon, SquareArrowExpand01Icon } from "@icons";
import type { ArtifactCardData } from "@shared/chat";
import { useArtifact } from "@/features/artifacts/hooks/useArtifact";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { ArtifactViewer } from "@/features/chat/components/artifacts/ArtifactViewer";
import { useSidebarPreview } from "@/features/chat/hooks/useSidebarPreview";

interface ArtifactCardProps {
  card: ArtifactCardData;
}

/** An artifact in chat: its first draft as it streams, then the stored program, with an Open action. */
export function ArtifactCard({ card }: ArtifactCardProps) {
  const artifactId =
    card.status === "ready" ? (card.artifact_id ?? null) : null;
  const stored = useArtifact(artifactId);
  const preview = useSidebarPreview(
    artifactId ? (
      <ArtifactViewer artifactId={artifactId} title={card.title} />
    ) : null,
  );
  const program = stored.data?.program ?? card.program ?? "";
  const streaming = card.status === "streaming";

  return (
    <div className="w-full max-w-2xl rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-3">
        <Chip size="sm" variant="flat" className="capitalize">
          {card.kind}
        </Chip>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">
          {card.title}
        </p>
        {streaming ? <Spinner size="sm" aria-label="Writing" /> : null}
        {artifactId ? (
          <Button
            size="sm"
            variant="flat"
            startContent={<SquareArrowExpand01Icon size={14} />}
            onPress={preview.open}
          >
            Open
          </Button>
        ) : null}
      </div>
      {card.status === "failed" ? (
        <p className="flex items-center gap-2 rounded-2xl bg-zinc-900 p-3 text-sm text-red-400">
          <Alert01Icon size={16} />
          GAIA couldn't make this {card.kind}.
        </p>
      ) : (
        <div className="relative max-h-[28rem] overflow-hidden rounded-2xl bg-zinc-900 [mask-image:linear-gradient(to_bottom,black_75%,transparent)]">
          <LazyArtifactRenderer
            program={program}
            isStreaming={streaming}
            density="card"
          />
        </div>
      )}
      {preview.panel}
    </div>
  );
}
