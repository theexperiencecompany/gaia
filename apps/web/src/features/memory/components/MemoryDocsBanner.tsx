"use client";

import { AiBrain01Icon, ArrowRight02Icon } from "@icons";
import { PromoBanner } from "@/components/shared/PromoBanner";

export function MemoryDocsBanner() {
  return (
    <PromoBanner
      icon={<AiBrain01Icon className="h-6 w-6 text-primary" />}
      title="How GAIA Remembers"
      description="Learn how memory works, what the four memory types mean, and how to stay in control of what GAIA knows."
      primaryAction={{
        label: "Read the guide",
        icon: <ArrowRight02Icon className="h-4 w-4" />,
        href: "https://docs.heygaia.io/guides/memory",
      }}
    />
  );
}
