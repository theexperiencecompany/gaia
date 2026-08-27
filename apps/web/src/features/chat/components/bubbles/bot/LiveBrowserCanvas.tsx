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
    <div className="overflow-hidden rounded-xl bg-zinc-950 ring-1 ring-white/10">
      <canvas
        ref={canvasRef}
        tabIndex={interactive ? 0 : -1}
        className={`aspect-video w-full outline-none ${
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
