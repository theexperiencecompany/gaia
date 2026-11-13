"use client";

import { Spinner } from "@heroui/spinner";
import type { LiveBrowser } from "@/features/browser/hooks/useLiveBrowser";

interface LiveScreenProps {
  live: Pick<LiveBrowser, "canvasRef" | "status">;
  interactive: boolean;
}

/**
 * The live browser's screen: the canvas `useLiveBrowser` draws onto and, until
 * the stream is live, what it is waiting on. Every surface (chat card, side
 * panel, the bot user's live page) renders the screen through this.
 */
export function LiveScreen({ live, interactive }: LiveScreenProps) {
  return (
    <>
      {/* h-auto keeps the element at the frame's own aspect ratio (the canvas
          width/height attributes) — a forced CSS aspect stretches the image. */}
      <canvas
        ref={live.canvasRef}
        width={1280}
        height={800}
        tabIndex={interactive ? 0 : -1}
        className={`block h-auto w-full outline-none ${
          interactive ? "cursor-crosshair touch-none" : "pointer-events-none"
        }`}
      />
      {live.status !== "live" && (
        <div className="flex items-center gap-2 px-3 py-2 text-xs text-zinc-400">
          {live.status === "connecting" && (
            <Spinner size="sm" color="current" />
          )}
          {live.status === "closed"
            ? "This browser session has ended"
            : "Connecting…"}
        </div>
      )}
    </>
  );
}
