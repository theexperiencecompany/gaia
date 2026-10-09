// @vitest-environment jsdom
/**
 * The per-day price heading is master's "$1 a day to never work again." in
 * every state a reader can meet it: server HTML, hydrated DOM, and whatever
 * the plans API is doing. It quotes the advertised price that
 * scripts/payment_setup.py guards against Dodo, so no state can drop the price.
 */
import { cleanup, render } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Plan } from "@/features/pricing/api/pricingApi";

const plansQuery = {
  plans: [] as Plan[],
  plansLoading: false,
  error: null as Error | null,
};

vi.mock("@/features/pricing/hooks/usePricing", () => ({
  usePricing: () => ({
    plans: plansQuery.plans,
    plansLoading: plansQuery.plansLoading,
    isLoading: plansQuery.plansLoading,
    error: plansQuery.error,
    subscriptionStatus: undefined,
  }),
}));

import { ProDailyPriceHeading } from "@/features/pricing/components/ProDailyPriceHeading";

const LANDING = "$1 a day to never work again.";
const PRICING_PAGE = "$1 a day to never do busywork again.";

/** The live Pro monthly row at a price the advertised one does not match. */
const MOVED_PRO_MONTHLY: Plan = {
  id: "691d8f37091c87af56990f65",
  dodo_product_id: "pdt_monthly",
  name: "Pro",
  plan_type: "pro",
  description: "Everything GAIA does, in one plan.",
  amount: 4500,
  currency: "USD",
  duration: "monthly",
  max_users: 1,
  features: [],
  is_active: true,
  created_at: "2025-11-19T09:34:47.803000Z",
  updated_at: "2026-09-17T20:22:17.782000Z",
};

const landingHeading = (
  <ProDailyPriceHeading afterPrice="a day to never work again." />
);

function textOfServerHtml(html: string): string {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host.textContent ?? "";
}

afterEach(() => {
  cleanup();
  plansQuery.plans = [];
  plansQuery.plansLoading = false;
  plansQuery.error = null;
});

describe("per-day price heading", () => {
  it("server-renders master's exact string", () => {
    expect(renderToString(landingHeading)).toBe(LANDING);
  });

  it("server-renders the pricing page's exact string", () => {
    expect(
      renderToString(
        <ProDailyPriceHeading afterPrice="a day to never do busywork again." />,
      ),
    ).toBe(PRICING_PAGE);
  });

  it.each([
    ["loading", { plansLoading: true }],
    ["failed", { error: new Error("503") }],
    ["served", { plans: [MOVED_PRO_MONTHLY] }],
  ] as const)("reads the same while the plans query is %s", (_state, query) => {
    Object.assign(plansQuery, query);
    const { container } = render(landingHeading);
    expect(container.textContent).toBe(LANDING);
    expect(container.children).toHaveLength(0);
  });

  it("hydrates to exactly the server's output", () => {
    const serverText = textOfServerHtml(renderToString(landingHeading));
    plansQuery.plansLoading = true;
    const { container } = render(landingHeading);
    expect(container.textContent).toBe(serverText);
  });
});
