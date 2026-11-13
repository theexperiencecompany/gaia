// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

// Every deferred section is held back, as it is until it nears the viewport.
vi.mock("@/components/shared/HydrateOnVisible", () => ({
  HydrateOnVisible: () => null,
}));

// Each next/dynamic section renders a marker named after the module it loads.
vi.mock("next/dynamic", () => ({
  default: (loader: () => Promise<unknown>) => {
    const name = /sections\/(\w+)/.exec(loader.toString())?.[1] ?? "other";
    return () => <div data-testid={`section-${name}`} />;
  },
}));

vi.mock("next/image", () => ({ default: () => null }));
vi.mock("@/components/ui/ProgressiveImage", () => ({ default: () => null }));
vi.mock("@/features/landing/components/hero/HeroSection", () => ({
  default: () => null,
}));
vi.mock("@/features/landing/components/LazyMotionProvider", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import LandingPageClient from "@/app/[locale]/(landing)/client";

describe("landing page", () => {
  it("renders pricing at page load, not behind deferred hydration", () => {
    render(<LandingPageClient latestRelease={null} />);

    expect(screen.getByTestId("section-PricingSection")).toBeTruthy();
  });
});
