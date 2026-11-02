// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { domAnimation, LazyMotion } from "motion/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let preferences: { needs?: string[]; other_need?: string | null } | undefined;

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ onboarding: { preferences } }),
}));

import { PaywallValuePreview } from "@/features/onboarding/components/PaywallValuePreview";
import { NEED_WEEK_ONE } from "@/features/onboarding/constants/messages";

const wrap = (node: ReactNode) =>
  render(<LazyMotion features={domAnimation}>{node}</LazyMotion>);

describe("PaywallValuePreview", () => {
  beforeEach(() => {
    preferences = { needs: ["inbox", "founder_competitors"], other_need: null };
  });

  it("lists what GAIA does in week one for each pick the user made", () => {
    wrap(<PaywallValuePreview startingJobs={[]} jobsStillDrafting={false} />);
    expect(screen.getByText(NEED_WEEK_ONE.inbox)).toBeDefined();
    expect(screen.getByText(NEED_WEEK_ONE.founder_competitors)).toBeDefined();
    expect(screen.queryByText(NEED_WEEK_ONE.calendar)).toBeNull();
  });

  it("quotes the user's own words for a typed need", () => {
    preferences = { needs: [], other_need: "  invoices from clients  " };
    wrap(<PaywallValuePreview startingJobs={[]} jobsStillDrafting={false} />);
    expect(
      screen.getByText("And the thing you mentioned: invoices from clients"),
    ).toBeDefined();
  });

  it("shows the drafted jobs once they land", () => {
    wrap(
      <PaywallValuePreview
        startingJobs={["Clear Friday's inbox"]}
        jobsStillDrafting={false}
      />,
    );
    expect(screen.getByText("Clear Friday's inbox")).toBeDefined();
  });

  it("keeps the plan readable while the jobs are still drafting, with no spinner", () => {
    const { container } = wrap(
      <PaywallValuePreview startingJobs={[]} jobsStillDrafting />,
    );
    expect(screen.getByText(NEED_WEEK_ONE.inbox)).toBeDefined();
    expect(screen.getByText("We start with")).toBeDefined();
    expect(container.querySelector('[aria-label="Loading"]')).toBeNull();
  });

  it("drops the jobs row when the draft never landed", () => {
    wrap(<PaywallValuePreview startingJobs={[]} jobsStillDrafting={false} />);
    expect(screen.queryByText("We start with")).toBeNull();
  });
});
