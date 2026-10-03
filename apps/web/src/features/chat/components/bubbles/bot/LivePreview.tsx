"use client";

import { Button } from "@heroui/button";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import {
  EyeIcon,
  FullScreenIcon,
  SidebarRight01Icon,
  SquareArrowUpRight02Icon,
} from "@icons";
import { useState } from "react";
import { useLiveBrowser } from "@/features/browser/hooks/useLiveBrowser";
import type { LiveSurface } from "@/features/browser/types";
import { LiveScreen } from "./LiveScreen";
import { ShimmerText } from "./ShimmerText";

// The live browser in its own surface: the desktop expanded view is the
// right-side panel, the full-screen modal is the mobile fallback. While the
// panel shows this session the card hands the stream over (no double decode).
export function LivePreview({
  socketUrl,
  pageUrl,
  currentTask,
  onDropped,
  surface,
}: {
  socketUrl: string;
  pageUrl: string;
  currentTask?: string;
  onDropped: () => void;
  surface: LiveSurface;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  const inPanel = surface.kind === "panel";
  // One socket: the screen renders inline OR in the modal, never both at once.
  const live = useLiveBrowser(inPanel ? null : socketUrl, false, onDropped);
  const screen = (
    <div className="overflow-hidden rounded-xl bg-zinc-900">
      <LiveScreen live={live} interactive={false} />
    </div>
  );

  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="mb-2 flex items-center gap-1.5 px-0.5">
        <EyeIcon className="size-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Live preview</span>
        {surface.kind === "card" && (
          <Button
            isIconOnly
            size="sm"
            variant="light"
            radius="full"
            className="ml-auto size-6 min-w-6 text-zinc-400"
            aria-label="Open in side panel"
            onPress={surface.openPanel}
          >
            <SidebarRight01Icon className="size-4" />
          </Button>
        )}
        {surface.kind === "mobile" && (
          <Button
            isIconOnly
            size="sm"
            variant="light"
            radius="full"
            className="ml-auto size-6 min-w-6 text-zinc-400"
            aria-label="Full screen live preview"
            onPress={() => setFullscreen(true)}
          >
            <FullScreenIcon className="size-4" />
          </Button>
        )}
      </div>

      {inPanel ? (
        <div className="flex aspect-[8/5] w-full items-center justify-center rounded-xl bg-zinc-800 text-xs text-zinc-500">
          Streaming in the side panel
        </div>
      ) : (
        !fullscreen && screen
      )}

      {surface.kind === "card" && (
        <div className="mt-2 px-0.5">
          <Button
            size="sm"
            variant="light"
            radius="full"
            className="h-7 px-2 text-xs text-zinc-400"
            startContent={<SidebarRight01Icon className="size-3.5" />}
            onPress={surface.openPanel}
          >
            Open side panel
          </Button>
        </div>
      )}
      {surface.kind === "mobile" && (
        <div className="mt-2 px-0.5">
          <Button
            as="a"
            href={pageUrl}
            target="_blank"
            rel="noopener noreferrer"
            size="sm"
            variant="light"
            radius="full"
            className="h-7 px-2 text-xs text-zinc-400"
            startContent={<SquareArrowUpRight02Icon className="size-3.5" />}
          >
            Open full browser
          </Button>
        </div>
      )}

      <Modal
        isOpen={fullscreen}
        onOpenChange={setFullscreen}
        size="full"
        scrollBehavior="inside"
      >
        <ModalContent className="bg-zinc-950">
          <ModalBody className="flex flex-col gap-4 p-4 sm:p-6">
            <div className="flex min-h-0 flex-1 items-center justify-center">
              {fullscreen && <div className="w-full max-w-6xl">{screen}</div>}
            </div>
            {currentTask && (
              <div className="mx-auto w-full max-w-6xl shrink-0 rounded-2xl bg-zinc-900 px-4 py-3 text-sm">
                <ShimmerText text={currentTask} />
              </div>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </div>
  );
}
