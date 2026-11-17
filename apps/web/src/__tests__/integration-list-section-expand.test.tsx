// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Integration } from "@/features/integrations/types";

let integrations: Integration[] = [];

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({
    integrations,
    connectIntegration: vi.fn(),
    refetch: vi.fn(),
  }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    dismiss: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
  },
}));

import { IntegrationListSection } from "@/features/integrations/components/IntegrationListSection";

function available(id: string): Integration {
  return {
    id,
    name: id,
    description: `${id} integration`,
    category: "productivity",
    status: "not_connected",
    slug: id.toLowerCase(),
  };
}

function availableTrigger(): HTMLElement {
  return screen.getByRole("button", { name: /Available/ });
}

describe("IntegrationListSection", () => {
  beforeEach(() => {
    integrations = [];
  });

  it("opens Available when the integrations arrive after mount, then keeps the user's toggle", () => {
    const { rerender } = render(<IntegrationListSection />);

    integrations = [available("Notion"), available("Slack")];
    rerender(<IntegrationListSection />);
    expect(availableTrigger().getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(availableTrigger());
    expect(availableTrigger().getAttribute("aria-expanded")).toBe("false");

    integrations = [...integrations, available("Linear")];
    rerender(<IntegrationListSection />);
    expect(availableTrigger().getAttribute("aria-expanded")).toBe("false");
  });
});
