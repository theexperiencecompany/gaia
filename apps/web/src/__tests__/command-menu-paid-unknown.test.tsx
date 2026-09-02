// @vitest-environment jsdom
//
// Regression coverage for the "paying user sees free-tier UI on reload" bug
// in CommandMenu: the "Upgrade to Pro" item used `hideWhenSubscribed &&
// subscriptionStatus?.is_subscribed` off the raw (possibly disabled/never-
// fetched) subscription-status query, so a cold cache read `is_subscribed`
// as `undefined` — falsy — and a paying user reloading mid-fetch saw the
// upgrade prompt anyway. The fix routes through `useIsPaid()`: hide the
// upgrade item whenever the user is known-paid AND while plan status is
// still unknown (never show a free-tier CTA to a possibly-paid user).
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// cmdk measures rows via ResizeObserver, which jsdom doesn't implement.
class MockResizeObserver {
  observe() {
    // no-op: jsdom has no layout to observe
  }
  unobserve() {
    // no-op: jsdom has no layout to observe
  }
  disconnect() {
    // no-op: jsdom has no layout to observe
  }
}

let isPaid = false;
let isUnknown = false;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isUnknown }),
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {
    SEARCH_GLOBAL_OPENED: "search:global_opened",
    SEARCH_RESULT_CLICKED: "search:result_clicked",
  },
  trackEvent: vi.fn(),
}));

vi.mock("@/hooks/ui/usePlatform", () => ({
  usePlatform: () => ({ modifierKeyName: "cmd" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/chat/utils/newChatNavigation", () => ({
  prepareNewChat: vi.fn(),
}));

vi.mock("../api/searchApi", () => ({
  searchApi: {
    search: vi.fn().mockResolvedValue({
      conversations: [],
      messages: [],
      notes: [],
    }),
  },
}));

import CommandMenu from "@/features/search/components/CommandMenu";

describe("CommandMenu — Upgrade to Pro item vs. plan status unknown", () => {
  beforeAll(() => {
    (
      globalThis as unknown as { ResizeObserver: typeof MockResizeObserver }
    ).ResizeObserver = MockResizeObserver;
    // cmdk scrolls the active item into view on selection changes; jsdom
    // doesn't implement layout, so scrollIntoView doesn't exist.
    Element.prototype.scrollIntoView = vi.fn();
  });

  beforeEach(() => {
    isPaid = false;
    isUnknown = false;
  });

  it("shows 'Upgrade to Pro' for a known-free user", () => {
    render(<CommandMenu open onOpenChange={vi.fn()} />);

    expect(screen.getByText("Upgrade to Pro")).not.toBeNull();
  });

  it("hides 'Upgrade to Pro' for a known-paid user", () => {
    isPaid = true;
    render(<CommandMenu open onOpenChange={vi.fn()} />);

    expect(screen.queryByText("Upgrade to Pro")).toBeNull();
  });

  it("hides 'Upgrade to Pro' while the plan status is still unknown, instead of showing the free-tier CTA (cold-cache race)", () => {
    isPaid = false;
    isUnknown = true;
    render(<CommandMenu open onOpenChange={vi.fn()} />);

    // Before the fix, `subscriptionStatus?.is_subscribed` read as
    // `undefined` (falsy) in this exact window, so the item stayed visible
    // for a paying user reloading mid-fetch.
    expect(screen.queryByText("Upgrade to Pro")).toBeNull();
  });
});
