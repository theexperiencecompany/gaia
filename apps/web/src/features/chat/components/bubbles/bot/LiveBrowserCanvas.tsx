"use client";

import { Spinner } from "@heroui/spinner";
import { useLiveBrowser } from "@/features/browser/hooks/useLiveBrowser";
import { useIsMobile } from "@/hooks/ui/useMobile";
import { LiveKeyboard } from "./LiveKeyboard";

export function LiveBrowserCanvas({
  socketUrl,
  interactive,
  onDropped,
}: {
  socketUrl: string;
  interactive: boolean;
  /** The socket dropped: renew the token so the redial carries a live one. */
  onDropped?: () => void;
}) {
  const isMobile = useIsMobile();
  const { canvasRef, keyboardRef, openKeyboard, status } = useLiveBrowser(
    socketUrl,
    interactive,
    onDropped,
  );
  return (
    <div className="overflow-hidden rounded-xl bg-zinc-900">
      {/* h-auto keeps the element at the frame's own aspect ratio (the canvas
          width/height attributes) — a forced CSS aspect stretches the image. */}
      <canvas
        ref={canvasRef}
        width={1280}
        height={800}
        tabIndex={interactive ? 0 : -1}
        className={`block h-auto w-full outline-none ${
          interactive ? "cursor-crosshair touch-none" : "pointer-events-none"
        }`}
      />
      {interactive && isMobile && status === "live" && (
        <LiveKeyboard keyboardRef={keyboardRef} onOpen={openKeyboard} />
      )}
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
