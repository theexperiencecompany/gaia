"use client";

import type { ReactNode } from "react";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

export default function RecordingLayout({ children }: { children: ReactNode }) {
  return (
    <HeroUIProvider>
      <LazyMotionProvider>
        <QueryProvider>
          {/* Hide Next.js dev overlays and fix bubble widths for small recording viewports */}
          <style>{`
            nextjs-portal,
            #__next-build-watcher,
            [data-nextjs-devtools],
            [data-nextjs-toast],
            #__NEXTJS_PORTAL__ { display: none !important; }

            /* Override vw-based bubble constraints for recording viewports.
               Production uses wide desktop viewports where 30vw/60vw look fine;
               recording at 390px needs percentage-based widths instead. */
            [data-recording-phase] .imessage-bubble {
              max-width: 82% !important;
            }
            [data-recording-phase] .imessage-bubble > div {
              max-width: none !important;
            }
          `}</style>
          {children}
        </QueryProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
