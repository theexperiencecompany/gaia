// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getPrefs = vi.fn();

vi.mock("@/features/settings/api/approvalsApi", () => ({
  approvalsApi: {
    getHilPreferences: () => getPrefs(),
    putHilPreferences: vi.fn(),
    setToolOverride: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import type { HilMode } from "@shared/chat";
import { PermissionModeDecision } from "@/features/integrations/components/PermissionModeDecision";
import { PermissionToolList } from "@/features/integrations/components/PermissionToolList";
import type { IntegrationPermissions } from "@/features/integrations/hooks/useIntegrationPermissions";
import { HilApprovalMode } from "@/features/settings/components/HilApprovalMode";
import {
  ALWAYS_ASKS_NOTE,
  APPROVAL_MODES,
} from "@/features/settings/config/approvalModes";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function permissions(mode: HilMode): IntegrationPermissions {
  return {
    mode,
    changeMode: vi.fn(async () => undefined),
    isSavingMode: false,
    asks: () => true,
    askCount: 1,
    toggle: vi.fn(),
    deviations: 0,
    resetToDefaults: vi.fn(),
    isSavingTools: false,
  };
}

describe("approval mode wording", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names the three modes in plain words", () => {
    expect(APPROVAL_MODES.map((m) => [m.mode, m.label])).toEqual([
      ["always_ask", "Ask every time"],
      ["auto", "Ask when unsure"],
      ["always_allow", "Never ask"],
    ]);
    expect(
      APPROVAL_MODES.find((m) => m.mode === "auto")?.description,
    ).not.toMatch(/decline|refuse/i);
  });

  it("settings and the integration modal show the same labels and descriptions", async () => {
    for (const option of APPROVAL_MODES) {
      getPrefs.mockResolvedValue({
        mode: option.mode,
        tool_overrides: {},
        never_auto_tools: [],
      });
      const settings = render(<HilApprovalMode />, { wrapper });
      expect(
        await within(settings.container).findByText(option.description),
      ).toBeTruthy();
      expect(
        within(settings.container).getAllByText(option.label).length,
      ).toBeGreaterThan(0);
      expect(
        within(settings.container).getByText(ALWAYS_ASKS_NOTE),
      ).toBeTruthy();
      settings.unmount();
    }

    const modal = render(
      <PermissionModeDecision
        integrationName="Gmail"
        permissions={permissions("auto")}
      />,
    );
    for (const option of APPROVAL_MODES) {
      expect(within(modal.container).getByText(option.label)).toBeTruthy();
      expect(
        within(modal.container).getByText(option.description),
      ).toBeTruthy();
    }
  });

  it("the never-ask banner says what its button does, and the button does it", () => {
    const perms = permissions("always_allow");
    render(<PermissionToolList tools={[]} permissions={perms} />);
    const button = screen.getByRole("button", {
      name: "Switch to Ask when unsure",
    });
    fireEvent.click(button);
    expect(perms.changeMode).toHaveBeenCalledWith("auto");
  });

  it("shows no banner when GAIA already asks", () => {
    render(<PermissionToolList tools={[]} permissions={permissions("auto")} />);
    expect(
      screen.queryByRole("button", { name: "Switch to Ask when unsure" }),
    ).toBeNull();
  });
});
