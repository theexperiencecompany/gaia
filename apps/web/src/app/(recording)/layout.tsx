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

            /* Remove vw-based max-width so bubbles fill the parent flex container
               naturally. At 390px, 60vw = 234px which is far too narrow.
               The parent (chatbubblebot_parent flex-1) already bounds the width. */
            [data-recording-phase] .imessage-bubble {
              max-width: none !important;
            }

            /* Inner text wrapper inside user bubbles has max-w-[30vw] = 117px.
               Remove it so text fills the bubble. */
            [data-recording-phase] .imessage-bubble > div {
              max-width: none !important;
            }

            /* TodoSection cards have hard-coded min-w-[400/450px] that overflow
               the 390px recording viewport. Make them fill available space. */
            [data-recording-phase] .min-w-\\[400px\\],
            [data-recording-phase] .min-w-\\[450px\\] {
              min-width: 0 !important;
              width: 100% !important;
            }
          `}</style>
          {children}
        </QueryProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
