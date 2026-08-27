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
import { LiveBrowserCanvas } from "./LiveBrowserCanvas";
import { ShimmerText } from "./ShimmerText";

// The live browser, in its own surface. On desktop the expanded view is the
// right-side browser panel (chat shrinks next to it); the full-screen modal is
// the mobile fallback. While the side panel is showing this session the card
// hands the stream over instead of decoding the same frames twice.
export function LivePreview({
  socketUrl,
  pageUrl,
  currentTask,
  inPanel = false,
  onOpenPanel,
}: {
  socketUrl: string;
  pageUrl: string;
  currentTask?: string;
  /** This session is currently streaming in the side panel. */
  inPanel?: boolean;
  /** Open the side panel (undefined on mobile — falls back to the modal). */
  onOpenPanel?: () => void;
}) {
  const [fullscreen, setFullscreen] = useState(false);
  // One socket: the canvas mounts inline OR in the modal, never both at once.
  const canvas = (
    <LiveBrowserCanvas socketUrl={socketUrl} interactive={false} />
  );

  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="mb-2 flex items-center gap-1.5 px-0.5">
        <EyeIcon className="size-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">Live preview</span>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          radius="full"
          className="ml-auto size-6 min-w-6 text-zinc-400"
          aria-label={
            onOpenPanel ? "Open in side panel" : "Full screen live preview"
          }
          onPress={() => (onOpenPanel ? onOpenPanel() : setFullscreen(true))}
        >
          {onOpenPanel ? (
            <SidebarRight01Icon className="size-4" />
          ) : (
            <FullScreenIcon className="size-4" />
          )}
        </Button>
      </div>

      {inPanel ? (
        <Button
          onPress={onOpenPanel}
          variant="flat"
          className="aspect-[8/5] h-auto w-full rounded-xl bg-zinc-950 text-xs text-zinc-500 ring-1 ring-white/10"
        >
          Streaming in the side panel
        </Button>
      ) : (
        !fullscreen && canvas
      )}

      {!inPanel && (
        <div className="mt-2 px-0.5">
          {onOpenPanel ? (
            <Button
              size="sm"
              variant="light"
              radius="full"
              className="h-7 px-2 text-xs text-zinc-400"
              startContent={<SidebarRight01Icon className="size-3.5" />}
              onPress={onOpenPanel}
            >
              Open side panel
            </Button>
          ) : (
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
          )}
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
              {fullscreen && <div className="w-full max-w-6xl">{canvas}</div>}
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
