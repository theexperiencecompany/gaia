"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Cancel01Icon } from "@icons";
import { usePanelDrawsClose } from "@/components/layout/sidebar/RightSidebarSlot";
import { useArtifact } from "@/features/artifacts/hooks/useArtifact";
import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";
import { useCloseRightSidebar } from "@/stores/layoutStore";

interface ArtifactViewerProps {
  artifactId: string;
  title: string;
}

/** A stored artifact in the right-sidebar viewer. */
export function ArtifactViewer({ artifactId, title }: ArtifactViewerProps) {
  const { data, isPending, error } = useArtifact(artifactId, true);
  const closeSidebar = useCloseRightSidebar();
  const drawsClose = usePanelDrawsClose();

  return (
    <div className="flex h-full min-h-0 flex-col bg-zinc-900">
      <div className="flex min-h-12 shrink-0 items-center gap-2 bg-zinc-800 px-3">
        <p className="min-w-0 flex-1 truncate text-sm text-zinc-200">{title}</p>
        <ShareLinkControls
          iconOnly
          targetType="openui_artifact"
          targetId={artifactId}
        />
        {drawsClose && (
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={closeSidebar}
            aria-label="Close artifact"
          >
            <Cancel01Icon size={16} />
          </Button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        {isPending ? (
          <div className="flex justify-center p-10">
            <Spinner size="sm" />
          </div>
        ) : error ? (
          <p className="p-6 text-sm text-red-400">{error.message}</p>
        ) : (
          <LazyArtifactRenderer program={data.program} />
        )}
      </div>
    </div>
  );
}
