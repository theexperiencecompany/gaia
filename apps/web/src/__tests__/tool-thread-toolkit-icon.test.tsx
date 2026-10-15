// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import UnifiedToolThread from "@/features/chat/components/bubbles/bot/UnifiedToolThread";

const ATTIO_LOGO = "https://logos.composio.dev/api/attio";

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({
    integrations: [{ id: "attio", name: "Attio", iconUrl: ATTIO_LOGO }],
  }),
}));

/**
 * A Composio toolkit enabled from the catalog has no icon in code; its logo
 * lives on the integration. Its tool calls stream the registry category, the
 * toolkit name ("ATTIO"), while the integration id is the slug ("attio").
 */
describe("UnifiedToolThread with a catalog-enabled Composio toolkit", () => {
  it("shows the toolkit's logo on its tool calls", () => {
    const call = (id: string): ToolCallEntry => ({
      tool_name: "ATTIO_LIST_RECORDS",
      tool_category: "ATTIO",
      message: "",
      tool_call_id: id,
    });

    const { container } = render(
      <UnifiedToolThread
        timeline={[
          { kind: "tool", data: call("a") },
          { kind: "tool", data: call("b") },
        ]}
        isStreaming={false}
        pendingApprovalToolCallIds={new Set()}
        approvalOutcomeByToolCallId={new Map()}
      />,
    );

    const logo = container.querySelector("img");
    expect(logo?.getAttribute("src")).toContain(encodeURIComponent(ATTIO_LOGO));
  });
});
