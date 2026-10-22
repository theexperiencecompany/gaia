// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import UnifiedToolThread from "@/features/chat/components/bubbles/bot/UnifiedToolThread";

const ATTIO_LOGO = "https://logos.composio.dev/api/attio";

/**
 * A Composio toolkit enabled from the catalog has no icon in code; the backend
 * puts its logo and name on each of its tool calls.
 */
describe("UnifiedToolThread with a catalog-enabled Composio toolkit", () => {
  const call = (id: string): ToolCallEntry => ({
    tool_name: "ATTIO_LIST_RECORDS",
    tool_category: "attio",
    message: "",
    tool_call_id: id,
    icon_url: ATTIO_LOGO,
    integration_name: "Attio",
  });

  it("shows the logo the tool call carries", () => {
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

    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      encodeURIComponent(ATTIO_LOGO),
    );
  });
});
