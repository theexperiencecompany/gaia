"use client";

import { Spinner } from "@heroui/spinner";
import { useLiveBrowser } from "@/features/browser/hooks/useLiveBrowser";

export function LiveBrowserCanvas({
  socketUrl,
  interactive,
}: {
  socketUrl: string;
  interactive: boolean;
}) {
  const { canvasRef, status } = useLiveBrowser(socketUrl, interactive);
  return (
    <div className="overflow-hidden rounded-xl bg-zinc-900">
      {/* h-auto keeps the element at the frame's own aspect ratio (the canvas
          width/height attributes) — a forced CSS aspect stretches the image. */}
      <canvas
        ref={canvasRef}
        width={1280}
        height={800}
        tabIndex={interactive ? 0 : -1}
        className={`h-auto w-full outline-none ${
          interactive ? "cursor-crosshair" : "pointer-events-none"
        }`}
      />
      {status !== "live" && (
        <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-zinc-400">
          {status === "connecting" && <Spinner size="sm" color="current" />}
          {status === "closed"
            ? "This browser session has ended"
            : "Connecting…"}
        </div>
      )}
    </div>
  );
}
