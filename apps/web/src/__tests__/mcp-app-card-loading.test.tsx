// @vitest-environment jsdom
/** While the MCP app chunk loads, its card shows a local placeholder instead of blanking the messages around it. */
import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import type { MCPAppData } from "@/config/registries/toolRegistry";
import { renderTool } from "@/features/chat/components/bubbles/bot/TextBubble/ToolRenderers";

// The app-router next/dynamic, which production resolves next/dynamic to; the
// pages-router build vitest would otherwise load never suspends.
vi.mock("next/dynamic", async () => ({
  default: (
    await vi.importActual<{ default: typeof import("next/dynamic").default }>(
      "next/dist/shared/lib/app-dynamic",
    )
  ).default,
}));

// The chunk never arrives, so the card stays in its loading state.
vi.mock(
  "@/features/chat/components/tools/MCPAppRenderer",
  () => new Promise<never>(() => undefined),
);

const MCP_APP: MCPAppData = {
  tool_call_id: "call_1",
  tool_name: "show_chart",
  server_url: "https://mcp.example.com",
  resource_uri: "ui://chart",
  html_content: "<p>chart</p>",
};

describe("MCP app card while its chunk loads", () => {
  it("keeps the neighbouring message and shows a placeholder card", async () => {
    render(
      <Suspense fallback={<p>ancestor fallback</p>}>
        <p>earlier message</p>
        {renderTool("mcp_app", MCP_APP)}
      </Suspense>,
    );

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText("earlier message")).toBeTruthy();
    expect(screen.queryByText("ancestor fallback")).toBeNull();
  });
});
