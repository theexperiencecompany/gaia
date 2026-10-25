// @vitest-environment jsdom
/** The rate-limit card sells upgrades only where the instance bills; a self-host instance sells nothing. */

import type { RateLimitData } from "@shared/chat";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const deployment = vi.hoisted(() => ({ bills: true }));

vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useDeployment: () => deployment,
}));

import { useRateLimitCard } from "@/features/chat/hooks/useRateLimitCard";

const LIMITED = {
  feature: "deep_research",
  plan_required: "pro",
  current_plan: "free",
} as RateLimitData;

describe("useRateLimitCard", () => {
  it("offers the upgrade where the instance bills", () => {
    deployment.bills = true;
    const { result } = renderHook(() => useRateLimitCard(LIMITED));

    expect(result.current.showFooter).toBe(true);
    expect(result.current.showUpgradeNudge).toBe(true);
  });

  it("offers nothing to buy where the instance does not bill", () => {
    deployment.bills = false;
    const { result } = renderHook(() => useRateLimitCard(LIMITED));

    expect(result.current.showFooter).toBe(false);
    expect(result.current.showUpgradeNudge).toBe(false);
  });

  it("drops the footer for a pro user at a daily cap", () => {
    deployment.bills = true;
    const { result } = renderHook(() =>
      useRateLimitCard({
        feature: "chat",
        current_plan: "pro",
      } as RateLimitData),
    );

    expect(result.current.showFooter).toBe(false);
  });
});
