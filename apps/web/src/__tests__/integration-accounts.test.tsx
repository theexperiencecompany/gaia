// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getAccounts = vi.fn();
const updateAccount = vi.fn();
const removeAccount = vi.fn();

vi.mock("@/features/integrations/api/integrationsApi", () => ({
  integrationsApi: {
    getIntegrationAccounts: (id: string) => getAccounts(id),
    updateIntegrationAccount: (id: string, accountId: string, body: unknown) =>
      updateAccount(id, accountId, body),
    removeIntegrationAccount: (id: string, accountId: string) =>
      removeAccount(id, accountId),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Its keyboard handling needs React's useEffectEvent, which the test runtime
// lacks; the dialog is not what these tests are about.
vi.mock("@/components/shared/ConfirmationDialog", () => ({
  ConfirmationDialog: () => null,
}));

import type { IntegrationAccountsResponse } from "@shared/api/generated";
import { IntegrationAccounts } from "@/components/layout/sidebar/right-variants/integration-sidebar/IntegrationAccounts";
import { integrationKeys } from "@/features/integrations/api/queryKeys";
import { useIntegrationAccounts } from "@/features/integrations/hooks/useIntegrationAccounts";
import type { Integration } from "@/features/integrations/types";

function accountsResponse(
  overrides: Partial<IntegrationAccountsResponse> = {},
): IntegrationAccountsResponse {
  return {
    integrationId: "gmail",
    maxAccounts: 5,
    accounts: [
      {
        id: "ca_work",
        label: "work@acme.com",
        nickname: null,
        displayName: "work@acme.com",
        status: "connected",
        isPrimary: true,
        connectedAt: "2026-10-01T00:00:00Z",
        expiredAt: null,
      },
      {
        id: "ca_home",
        label: "me@gmail.com",
        nickname: "Personal",
        displayName: "Personal",
        status: "expired",
        isPrimary: false,
        connectedAt: "2026-10-02T00:00:00Z",
        expiredAt: "2026-10-05T00:00:00Z",
      },
    ],
    ...overrides,
  };
}

const gmail: Integration = {
  id: "gmail",
  name: "Gmail",
  description: "Email",
  category: "communication",
  status: "connected",
  managedBy: "composio",
  slug: "gmail",
};

describe("connected accounts", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("lists every account, marking the primary and the expired one", async () => {
    getAccounts.mockResolvedValue(accountsResponse());

    render(<IntegrationAccounts integration={gmail} onConnect={vi.fn()} />, {
      wrapper,
    });

    expect(await screen.findByText("work@acme.com")).toBeTruthy();
    expect(screen.getByText("Personal")).toBeTruthy();
    // The nickname hides the address, so the address is shown beneath it.
    expect(screen.getByText("me@gmail.com")).toBeTruthy();
    expect(screen.getByText("Primary")).toBeTruthy();
    expect(screen.getByText("Expired")).toBeTruthy();
    expect(getAccounts).toHaveBeenCalledWith("gmail");
  });

  it("stops offering another account at the limit", async () => {
    getAccounts.mockResolvedValue(accountsResponse({ maxAccounts: 2 }));

    render(<IntegrationAccounts integration={gmail} onConnect={vi.fn()} />, {
      wrapper,
    });

    const button = await screen.findByRole("button", {
      name: /2 accounts connected/,
    });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("making an account primary sends only that and refreshes the integrations", async () => {
    const promoted = accountsResponse({
      accounts: accountsResponse().accounts.map((account) => ({
        ...account,
        isPrimary: account.id === "ca_home",
      })),
    });
    getAccounts
      .mockResolvedValueOnce(accountsResponse())
      .mockResolvedValue(promoted);
    updateAccount.mockResolvedValue(promoted);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useIntegrationAccounts("gmail"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.accounts).toHaveLength(2));
    await act(() => result.current.makePrimary("ca_home"));

    expect(updateAccount).toHaveBeenCalledWith("gmail", "ca_home", {
      isPrimary: true,
    });
    expect(queryClient.getQueryData(integrationKeys.accounts("gmail"))).toEqual(
      promoted,
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: integrationKeys.all });
  });

  it("disconnecting an account revokes exactly that one", async () => {
    const remaining = accountsResponse({
      accounts: accountsResponse().accounts.slice(0, 1),
    });
    getAccounts
      .mockResolvedValueOnce(accountsResponse())
      .mockResolvedValue(remaining);
    removeAccount.mockResolvedValue(remaining);

    const { result } = renderHook(() => useIntegrationAccounts("gmail"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.accounts).toHaveLength(2));
    await act(() => result.current.remove("ca_home"));

    expect(removeAccount).toHaveBeenCalledWith("gmail", "ca_home");
    await waitFor(() => expect(result.current.accounts).toHaveLength(1));
  });
});
