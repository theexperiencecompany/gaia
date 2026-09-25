"use client";

import { useMemo } from "react";
import { RecapSlideshow } from "@/components/browser/RecapSlideshow";
import type { BrowserStepSnapshot } from "@/types/features/browserTaskTypes";

// Once the task is done the live view would 404, so the card replays the
// captured step screenshots as a slideshow — the in-card twin of the shared
// recap page (services/browser/replay.py).
export function RecapViewer({ steps }: { steps: BrowserStepSnapshot[] }) {
  const shots = useMemo(
    () =>
      steps.flatMap((s) =>
        s.screenshot
          ? [
              {
                index: s.index,
                url: s.screenshot,
                caption: s.goal,
                // The pulse marks where the agent acted — the first action on
                // this step that resolved to an on-screen point.
                point: s.actions?.find((a) => a.point)?.point ?? null,
              },
            ]
          : [],
      ),
    [steps],
  );
  return <RecapSlideshow shots={shots} />;
}
