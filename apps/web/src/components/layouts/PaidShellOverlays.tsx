"use client";

import nextDynamic from "next/dynamic";
import { useState } from "react";

const CommandMenu = nextDynamic(
  () => import("@/features/search/components/CommandMenu"),
  { ssr: false },
);

const FirstStepsWidget = nextDynamic(
  () =>
    import("@/features/first-steps").then((m) => ({
      default: m.FirstStepsWidget,
    })),
  { ssr: false },
);

const WhatsNewModal = nextDynamic(
  () =>
    import("@/features/whats-new/components/WhatsNewModal").then((m) => ({
      default: m.WhatsNewModal,
    })),
  { ssr: false },
);

/** The app shell's floating surfaces, each reading paid-only data. */
export function PaidShellOverlays() {
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);

  return (
    <>
      <WhatsNewModal />

      {/* Activation checklist; hides itself on /onboarding and /dashboard */}
      <FirstStepsWidget />

      <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
    </>
  );
}
