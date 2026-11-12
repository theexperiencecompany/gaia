import type { ReactNode } from "react";
import { useCallback, useState } from "react";

import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import { useIsMobile } from "@/hooks/ui/useMobile";
import type { RightSidebarMode } from "@/stores/layoutStore.types";

const SHEET_MAX_WIDTH = 768;

interface SidebarPreview {
  open: () => void;
  /** Render this alongside the trigger; it portals into the right sidebar while open. */
  panel: ReactNode;
}

/** Open content in the right-sidebar viewer: the artifact panel on desktop, a sheet on small screens. */
export function useSidebarPreview(content: ReactNode): SidebarPreview {
  const [mode, setMode] = useState<RightSidebarMode | null>(null);
  const isMobile = useIsMobile();

  const open = useCallback(() => {
    const useSheet = isMobile || window.innerWidth < SHEET_MAX_WIDTH;
    setMode(useSheet ? "sheet" : "artifact");
  }, [isMobile]);

  const close = useCallback(() => setMode(null), []);

  const panel = mode && (
    <RightSidebarPanel mode={mode} onClose={close}>
      {content}
    </RightSidebarPanel>
  );

  return { open, panel };
}
