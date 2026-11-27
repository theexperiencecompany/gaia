"use client";

import { Chip, Skeleton, Spinner } from "@heroui/react";
import { Alert01Icon, SquareArrowExpand01Icon } from "@icons";
import type { ArtifactCardData } from "@shared/chat";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useArtifact } from "@/features/artifacts/hooks/useArtifact";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { ArtifactViewer } from "@/features/chat/components/artifacts/ArtifactViewer";
import { useSidebarPreview } from "@/features/chat/hooks/useSidebarPreview";

interface ArtifactCardProps {
  card: ArtifactCardData;
}

const NOTICE_CLASSES =
  "flex items-center gap-2 rounded-2xl bg-zinc-900 p-3 text-sm";

function failureMessage(card: ArtifactCardData): string {
  return card.reason === "truncated"
    ? `This ${card.kind} was too long to finish. Ask for a shorter one, or split it into parts.`
    : `GAIA couldn't make this ${card.kind}.`;
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

  const body = () => {
    if (card.status === "failed") {
      return (
        <p className={`${NOTICE_CLASSES} text-red-400`}>
          <Alert01Icon size={16} />
          {failureMessage(card)}
        </p>
      );
    }
    if (card.status === "stopped") {
      return (
        <p className={`${NOTICE_CLASSES} text-zinc-400`}>
          Stopped before this {card.kind} was finished.
        </p>
      );
    }
    // A reloaded turn keeps only the done frame, so the program comes from the store.
    if (!program && stored.isError) {
      return (
        <div className={`${NOTICE_CLASSES} justify-between text-zinc-400`}>
          <span className="flex items-center gap-2">
            <Alert01Icon size={16} />
            Couldn't load this {card.kind}.
          </span>
          <GaiaButton
            size="sm"
            variant="default-soft"
            onPress={() => stored.refetch()}
          >
            Try again
          </GaiaButton>
        </div>
      );
    }
    if (!program) {
      return (
        <div
          role="status"
          aria-label={`Loading ${card.kind}`}
          aria-busy="true"
          className="rounded-2xl bg-zinc-900 p-3"
        >
          <Skeleton className="h-64 w-full rounded-2xl" />
        </div>
      );
    }
    return (
      <div className="relative max-h-[28rem] overflow-hidden rounded-2xl bg-zinc-900 [mask-image:linear-gradient(to_bottom,black_75%,transparent)]">
        <LazyArtifactRenderer
          program={program}
          isStreaming={streaming}
          density="card"
        />
      </div>
    );
  };

  return (
    <div className="w-full max-w-2xl rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-3">
        <Chip size="sm" variant="soft">
          <Chip.Label className="capitalize">{card.kind}</Chip.Label>
        </Chip>
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-100">
          {card.title}
        </p>
        {streaming ? <Spinner size="sm" aria-label="Writing" /> : null}
        {artifactId ? (
          <GaiaButton size="sm" variant="default-soft" onPress={preview.open}>
            <SquareArrowExpand01Icon size={14} />
            Open
          </GaiaButton>
        ) : null}
      </div>
      {body()}
      {preview.panel}
    </div>
  );
}
