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
        integration_name: "Custom",
        message: "Connect it",
        expired: false,
        add_account: false,
        connected_accounts: [],
        reconnect_account: null,
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
      expect(connectIntegration).toHaveBeenCalledWith("custom-bearer", {
        bearerToken: "sk-test-123",
        accountId: undefined,
      }),
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
      expect(connectIntegration).toHaveBeenCalledWith("custom-oauth", {
        bearerToken: undefined,
        accountId: undefined,
      }),
    );
  });

  it("shows a loading header (from the streamed name) until the catalog resolves", () => {
    integrations = [];
    renderCard("custom-bearer");
    // No catalog entry yet: the header shows the streamed integration_name.
    expect(screen.getByText("Custom")).toBeDefined();
  });
});

describe("IntegrationConnectionPrompt — adding another account", () => {
  beforeEach(() => {
    connectIntegration.mockReset();
    integrations = [];
  });

  it("keeps an Add account button on an integration that is already connected", async () => {
    connectIntegration.mockResolvedValue({ status: "redirecting" });
    integrations = [
      {
        ...oauthIntegration(),
        id: "gmail",
        name: "Gmail",
        status: "connected",
        source: "platform",
      },
    ];
    render(
      <IntegrationConnectionPrompt
        integration_connection_required={{
          integration_id: "gmail",
          integration_name: "Gmail",
          message: "Add another Gmail account.",
          expired: false,
          add_account: true,
          connected_accounts: ["Work", "me@gmail.com"],
          reconnect_account: null,
        }}
      />,
    );

    expect(screen.getByText("Already connected")).toBeDefined();
    expect(screen.getByText("Work")).toBeDefined();
    expect(screen.getByText("me@gmail.com")).toBeDefined();
    expect(screen.getByText("Connected")).toBeDefined();
    expect(screen.getByText("Add another Gmail account.")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));

    await waitFor(() =>
      expect(connectIntegration).toHaveBeenCalledWith("gmail", {
        bearerToken: undefined,
        accountId: undefined,
      }),
    );
  });

  it("signs the named expired account back in on a connected integration", async () => {
    connectIntegration.mockResolvedValue({ status: "redirecting" });
    integrations = [
      {
        ...oauthIntegration(),
        id: "gmail",
        name: "Gmail",
        status: "connected",
        source: "platform",
      },
    ];
    render(
      <IntegrationConnectionPrompt
        integration_connection_required={{
          integration_id: "gmail",
          integration_name: "Gmail",
          message: "Your Gmail account work@acme.com lost its connection.",
          expired: true,
          add_account: false,
          connected_accounts: [],
          reconnect_account: { id: "ca_work", name: "work@acme.com" },
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() =>
      expect(connectIntegration).toHaveBeenCalledWith("gmail", {
        bearerToken: undefined,
        accountId: "ca_work",
      }),
    );
  });
});

function connectorIntegration() {
  return {
    ...bearerIntegration(),
    id: "fly",
    name: "Fly.io",
    description: "Generic description",
    managedBy: "connector",
    connector: {
      kind: "cli",
      capability: "Deploy and manage your Fly.io apps",
      providerDomain: "fly.io",
      allowedHosts: ["api.fly.io", "api.machines.dev"],
      keyLabel: "API token",
      tokenUrl: "https://fly.io/user/personal_access_tokens",
      verified: true,
    },
  };
}

describe("IntegrationConnectionPrompt — connector key entry", () => {
  beforeEach(() => {
    connectIntegration.mockReset();
    integrations = [connectorIntegration()];
  });

  it("offers Connect, not Retry, on a connector saved but never connected", () => {
    integrations = [{ ...connectorIntegration(), status: "created" }];

    renderCard("fly");

    expect(screen.getByRole("button", { name: "Connect" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("shows the capability, every host the key reaches and where to get the key", () => {
    renderCard("fly");

    expect(
      screen.getByText("Deploy and manage your Fly.io apps"),
    ).toBeDefined();
    expect(screen.queryByText("Generic description")).toBeNull();
    expect(screen.getByText("Your key goes only to:")).toBeDefined();
    expect(screen.getByText("api.fly.io")).toBeDefined();
    expect(screen.getByText("api.machines.dev")).toBeDefined();
    const link = screen.getByRole("link", { name: /get your api token/i });
    expect(link.getAttribute("href")).toBe(
      "https://fly.io/user/personal_access_tokens",
    );
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByLabelText("API token")).toBeDefined();
  });

  it("says Verifying while the key is checked, then who it connected as", async () => {
    const verification = Promise.withResolvers<unknown>();
    connectIntegration.mockReturnValue(verification.promise);
    renderCard("fly");

    fireEvent.change(screen.getByLabelText("API token"), {
      target: { value: "fo1_secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(await screen.findByText("Verifying…")).toBeDefined();
    verification.resolve({
      status: "connected",
      toolsCount: null,
      accountLabel: "ada@fly.io",
    });

    expect(await screen.findByText("Connected as ada@fly.io")).toBeDefined();
    expect(screen.queryByLabelText("API token")).toBeNull();
  });

  it("shows the server's fix in the card and keeps the field to retry", async () => {
    const fix =
      "Fly.io refused this API token. Copy the whole token and check it hasn't expired";
    connectIntegration.mockRejectedValueOnce(new Error(fix));
    renderCard("fly");

    fireEvent.change(screen.getByLabelText("API token"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /connect/i }));

    expect(await screen.findByText(fix)).toBeDefined();
    expect(screen.getByLabelText("API token")).toBeDefined();
    expect(screen.getByRole("button", { name: /retry/i })).toBeDefined();
  });
});
