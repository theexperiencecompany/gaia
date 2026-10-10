// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import IntegrationConnectionPrompt from "@/features/chat/components/bubbles/bot/IntegrationConnectionPrompt";

/**
 * A token-required (bearer) MCP server must collect its token INLINE in the chat
 * card and connect from there — never a modal, never a chat message, never the
 * LLM. Submit calls connectIntegration(id, token); on success the card shows
 * "Connected" and the token is cleared. Remove the bearer input / inline connect
 * and these go red.
 */

const connectIntegration = vi.fn();
let integrations: Record<string, unknown>[] = [];

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations, connectIntegration }),
}));

vi.mock("@/components/shared/CollapsibleListWrapper", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("@/features/chat/utils/toolIcons", () => ({
  getToolCategoryIcon: () => null,
}));

function bearerIntegration() {
  return {
    id: "custom-bearer",
    name: "TokenMCP",
    description: "Needs a token",
    status: "not_connected",
    source: "custom",
    available: true,
    authType: "bearer",
    requiresAuth: true,
  };
}

function oauthIntegration() {
  return { ...bearerIntegration(), id: "custom-oauth", authType: "oauth" };
}

function renderCard(id: string) {
  return render(
    <IntegrationConnectionPrompt
      integration_connection_required={{
        integration_id: id,
        message: "Connect it",
        expired: false,
      }}
    />,
  );
}

describe("IntegrationConnectionPrompt — inline token entry", () => {
  beforeEach(() => {
    connectIntegration.mockReset();
    integrations = [];
  });

  it("collects the token in-card and connects with (id, token)", async () => {
    connectIntegration.mockResolvedValue({
      status: "connected",
      toolsCount: 2,
    });
    integrations = [bearerIntegration()];
    renderCard("custom-bearer");

    const input = screen.getByPlaceholderText("Paste API token");
    fireEvent.change(input, { target: { value: "sk-test-123" } });
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    await waitFor(() =>
      expect(connectIntegration).toHaveBeenCalledWith(
        "custom-bearer",
        "sk-test-123",
      ),
    );
    // success surfaces inline, no navigation/modal
    await screen.findByText("Connected");
    expect(screen.getByText("2 tools available")).toBeDefined();
  });

  it("shows the error inline and lets the user retry", async () => {
    connectIntegration.mockRejectedValueOnce(new Error("bad token"));
    integrations = [bearerIntegration()];
    renderCard("custom-bearer");

    fireEvent.change(screen.getByPlaceholderText("Paste API token"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(await screen.findByText("bad token")).toBeDefined();
    expect(screen.getByRole("button", { name: /retry/i })).toBeDefined();
  });

  it("uses the direct/OAuth path (no token input) for a non-bearer server", async () => {
    connectIntegration.mockResolvedValue({ status: "redirecting" });
    integrations = [oauthIntegration()];
    renderCard("custom-oauth");

    expect(screen.queryByPlaceholderText("Paste API token")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    await waitFor(() =>
      expect(connectIntegration).toHaveBeenCalledWith(
        "custom-oauth",
        undefined,
      ),
    );
  });

  it("shows a loading header (from the streamed name) until the catalog resolves", () => {
    integrations = [];
    renderCard("custom-bearer");
    // no catalog entry yet; the streamed integration_name is not set here, so it
    // falls back — the point is it renders instead of returning nothing.
    expect(screen.getByText("Integration")).toBeDefined();
  });
});
