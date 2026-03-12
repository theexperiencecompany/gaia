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
            /* Kill the initial white flash before React hydrates */
            html, body { background-color: #111111 !important; }

            /* Landscape (desktop) — center the chat column with comfortable gutters */
            @media (min-width: 900px) {
              [data-recording-phase] .flex-1.overflow-y-auto,
              [data-recording-phase] .shrink-0.px-2.pb-2 {
                max-width: 800px !important;
                width: 100% !important;
                margin-left: auto !important;
                margin-right: auto !important;
              }
            }

            @keyframes recording-slide-up {
              from { transform: translateY(10px); }
              to   { transform: translateY(0); }
            }

            /* Each new message/tool card slides up when mounted — no opacity so content is always visible */
            [data-recording-phase] .space-y-4 > * {
              animation: recording-slide-up 0.4s cubic-bezier(0.22, 1, 0.36, 1);
            }

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

            /* Hide GAIA logo column — target the min-w-10 shrink-0 placeholder div
               regardless of whether it contains the image (empty div still takes flex space) */
            [data-recording-phase] .min-w-10.shrink-0 {
              display: none !important;
            }

            /* Remove the 40px left indent on tool cards / follow-up actions
               (was there to clear the GAIA logo column, which is now hidden) */
            [data-recording-phase] .ml-10\\.75 {
              margin-left: 0 !important;
            }

            /* Remove left indent on loading indicator (pl-11.5 aligns with logo) */
            [data-recording-phase] .pl-11\\.5 {
              padding-left: 0.5rem !important;
            }

            /* Hide user profile photo: target only the 40px avatar wrapper div
               (the sibling that immediately follows the chat bubble container) */
            [data-recording-phase] .chat_bubble_container.user ~ .min-w-10 {
              display: none !important;
            }
          `}</style>
          {children}
        </QueryProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
