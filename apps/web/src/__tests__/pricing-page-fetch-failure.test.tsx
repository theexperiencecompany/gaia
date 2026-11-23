import { beforeEach, describe, expect, it, vi } from "vitest";

const { getPlansServer } = vi.hoisted(() => ({ getPlansServer: vi.fn() }));

vi.mock("@/features/pricing/lib/serverPricingApi", () => ({ getPlansServer }));
vi.mock("@/features/pricing/components/PricingPage", () => ({
  default: () => null,
}));
vi.mock("@/components/seo/JsonLd", () => ({ default: () => null }));

import Pricing from "@/app/[locale]/(landing)/pricing/page";

describe("pricing page plan fetch", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    getPlansServer.mockReset();
  });

  it("fails the render when the plan fetch fails, so ISR never caches empty plans", async () => {
    getPlansServer.mockRejectedValue(new Error("backend down"));
    await expect(Pricing()).rejects.toThrow("backend down");
  });

  it("passes fetched plans to the page", async () => {
    getPlansServer.mockResolvedValue([{ id: "pro" }]);
    const element = await Pricing();
    expect(element.props.children[1].props.initialPlans).toEqual([
      { id: "pro" },
    ]);
  });
});
