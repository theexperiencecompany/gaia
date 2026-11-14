// @vitest-environment jsdom
/**
 * "Setting up tools" follows the server's tools_setup for a just-connected MCP:
 * it shows while discovery runs and clears when the server reports it ready or
 * failed, saying so on failure. Fidelity: the catalog item goes through the real
 * toIntegration and the real heading; the websocket push that re-reads it is not run.
 */
import type { MyIntegrationItem } from "@shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IntegrationToolsHeading } from "@/components/layout/sidebar/right-variants/integration-sidebar/IntegrationToolsHeading";
import {
  isSettingUpTools,
  toIntegration,
} from "@/features/integrations/utils/catalog";

function connectedMcp(
  toolsSetup: MyIntegrationItem["toolsSetup"],
): MyIntegrationItem {
  return {
    id: "posthog",
    name: "PostHog",
    description: "Analytics",
    category: "analytics",
    source: "platform",
    managedBy: "mcp",
    status: "connected",
    requiresAuth: true,
    isFeatured: false,
    displayPriority: 0,
    available: true,
    toolCount: 0,
    cloneCount: 0,
    toolsSetup,
  };
}

function renderHeading(toolsSetup: MyIntegrationItem["toolsSetup"]) {
  const integration = toIntegration(connectedMcp(toolsSetup));
  const isSettling = isSettingUpTools(integration);
  return render(
    <IntegrationToolsHeading
      toolCount={0}
      isConnected
      showToolsSkeleton={isSettling}
      isSettling={isSettling}
      setupFailed={integration.toolsSetup === "failed"}
      onOpenPermissions={() => undefined}
    />,
  );
}

describe("the tools setup indicator", () => {
  it("shows while the server's discovery is running", () => {
    renderHeading("running");
    expect(screen.getByText("Setting up tools")).toBeDefined();
  });

  it("clears and says why when the server reports the discovery failed", () => {
    renderHeading("failed");
    expect(screen.queryByText("Setting up tools")).toBeNull();
    expect(
      screen.getByText(/couldn't load this integration's tools/i),
    ).toBeDefined();
  });

  it("clears without an error when the server reports it ready with no tools", () => {
    const { container } = renderHeading("ready");
    expect(container.textContent).toBe("");
  });

  it("does not wait on an integration no connect reported a discovery for", () => {
    expect(isSettingUpTools(toIntegration(connectedMcp(null)))).toBe(false);
  });
});
