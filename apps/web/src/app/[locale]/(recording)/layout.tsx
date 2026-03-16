"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";

export default function RecordingLayout({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <HeroUIProvider>
      <LazyMotionProvider>
        <QueryClientProvider client={queryClient}>
          {/* Hide Next.js dev overlays and fix bubble widths for small recording viewports */}
          <style>{`
            html, body, #__next, #__next > *, #__next > * > * { background-color: #111111 !important; height: 100%; margin: 0; }

            @keyframes recording-slide-up {
              from { transform: translateY(10px); }
              to   { transform: translateY(0); }
            }

            /* Each new message/tool card slides up when mounted */
            [data-recording-phase] .space-y-4 > * {
              animation: recording-slide-up 0.4s cubic-bezier(0.22, 1, 0.36, 1);
            }

            /* Hide Next.js dev overlays */
            nextjs-portal,
            #__next-build-watcher,
            [data-nextjs-devtools],
            [data-nextjs-toast],
            #__NEXTJS_PORTAL__ { display: none !important; }

            /* ── Mobile-only overrides ────────────────────────────────── */
            /* These strip the logo column, avatars, and vw-based widths
               that don't work at 390px. Desktop keeps them for accuracy. */

            [data-recording-viewport="mobile"] .imessage-bubble {
              max-width: none !important;
            }
            [data-recording-viewport="mobile"] .imessage-bubble > div {
              max-width: none !important;
            }

            [data-recording-viewport="mobile"] .min-w-\\[400px\\],
            [data-recording-viewport="mobile"] .min-w-\\[450px\\] {
              min-width: 0 !important;
              width: 100% !important;
            }

            /* Hide GAIA logo column on mobile */
            [data-recording-viewport="mobile"] .min-w-10.shrink-0 {
              display: none !important;
            }

            /* Remove logo-column indent on tool cards / loading on mobile */
            [data-recording-viewport="mobile"] .ml-10\\.75 {
              margin-left: 0 !important;
            }
            [data-recording-viewport="mobile"] .pl-11\\.5 {
              padding-left: 0.5rem !important;
            }

            /* Hide user avatar on mobile */
            [data-recording-viewport="mobile"] .chat_bubble_container.user ~ .min-w-10 {
              display: none !important;
            }

            /* Neutralize viewport-unit values that break with CSS zoom.
               With zoom, viewport units reference the physical viewport (e.g. 2880px)
               not the logical viewport (1440px), causing oversized elements. */
            [data-recording-phase] .conversation_history {
              min-height: 0 !important;
            }
            [data-recording-phase] .imessage-bubble {
              max-width: 100% !important;
            }
          `}</style>
          {children}
        </QueryClientProvider>
      </LazyMotionProvider>
    </HeroUIProvider>
  );
}
