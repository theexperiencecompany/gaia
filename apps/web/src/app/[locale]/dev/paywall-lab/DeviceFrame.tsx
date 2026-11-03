import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type FrameDevice = "desktop" | "mobile";

interface DeviceFrameProps {
  device: FrameDevice;
  children: ReactNode;
}

/** The onboarding page at desktop width, or a 390px phone. Concepts adapt to this container, not the viewport. */
export function DeviceFrame({ device, children }: DeviceFrameProps) {
  const isMobile = device === "mobile";
  return (
    <div
      className={cn(
        "mx-auto bg-zinc-900",
        isMobile ? "w-[406px] rounded-[44px] p-2" : "w-full rounded-3xl p-1.5",
      )}
    >
      <div
        data-frame={device}
        className={cn(
          "@container overflow-y-auto bg-primary-bg",
          isMobile ? "h-[780px] rounded-[36px]" : "h-[720px] rounded-[20px]",
        )}
      >
        <div
          className={cn(
            "mx-auto flex min-h-full max-w-xl flex-col",
            isMobile ? "px-5 pt-14" : "px-8 py-12",
          )}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
