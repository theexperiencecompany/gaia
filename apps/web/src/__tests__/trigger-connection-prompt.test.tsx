// @vitest-environment jsdom
/**
 * A trigger whose integration isn't connected always says so: the prompt names
 * the integration from the catalog, waits for it while it loads, and never
 * leaves the trigger's settings blank.
 */
import type { MyIntegrationItem } from "@shared/api/generated";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let integrations: MyIntegrationItem[] = [];
let isLoading = false;
const connectIntegration = vi.fn();

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations, isLoading, connectIntegration }),
}));

import { TriggerConnectionPrompt } from "@/features/workflows/triggers/components/TriggerConnectionPrompt";

const ASANA: MyIntegrationItem = {
  id: "asana",
  name: "Asana",
  description: "Asana integration",
  category: "productivity",
  status: "not_connected",
  managedBy: "composio",
  source: "platform",
  slug: "asana",
};

describe("TriggerConnectionPrompt", () => {
  beforeEach(() => {
    integrations = [];
    isLoading = false;
    connectIntegration.mockReset();
  });

  it("names the catalog's integration and connects it", () => {
    integrations = [ASANA];
    render(<TriggerConnectionPrompt integrationId="asana" />);

    expect(screen.getByText("Asana")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(connectIntegration).toHaveBeenCalledWith("asana");
  });

  it("holds a placeholder while the catalog loads, never a blank panel", () => {
    isLoading = true;
    const { container } = render(
      <TriggerConnectionPrompt integrationId="asana" />,
    );

    expect(container.firstChild).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says the integration is unavailable when the catalog has no entry", () => {
    render(<TriggerConnectionPrompt integrationId="asana" />);

    expect(
      screen.getByText(/isn't available on this GAIA instance/),
    ).toBeTruthy();
  });
});
