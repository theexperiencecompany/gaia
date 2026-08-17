"use client";

import { useMemo } from "react";
import { RecapSlideshow } from "@/components/browser/RecapSlideshow";
import type { BrowserStepSnapshot } from "@/types/features/browserTaskTypes";

// Once the task is done the live session is gone (its live view would 404), so
// the card replays the captured step screenshots instead — a navigable slideshow
// (main frame + prev/next + a filmstrip), the in-card twin of the shared recap
// page (services/browser/replay.py).
export function RecapViewer({ steps }: { steps: BrowserStepSnapshot[] }) {
  const shots = useMemo(
    () =>
      steps
        .filter((s) => Boolean(s.screenshot))
        .map((s) => ({
          index: s.index,
          url: s.screenshot as string,
          caption: s.goal,
        })),
    [steps],
  );
  return <RecapSlideshow shots={shots} />;
}
