// @vitest-environment jsdom
/**
 * Enabling a Composio toolkit sends exactly the credentials its auth config needs, and nothing
 * GAIA cannot connect is offered.
 */

import type { ComposioToolkitDetailResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchToolkit = vi.fn();
const enableToolkit = vi.fn();

vi.mock("@/features/settings/api/composioSetupApi", () => ({
  COMPOSIO_CATALOG_PAGE_SIZE: 50,
  composioSetupApi: {
    fetchToolkit: (slug: string) => fetchToolkit(slug),
    enableToolkit: (slug: string, credentials: Record<string, string>) =>
      enableToolkit(slug, credentials),
    disableToolkit: vi.fn(),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { ComposioToolkitDetail } from "@/features/settings/components/composio/ComposioToolkitDetail";

function detail(
  overrides: Partial<ComposioToolkitDetailResponse>,
): ComposioToolkitDetailResponse {
  return {
    toolkit: {
      slug: "affinity",
      name: "Affinity",
      description: "Relationship intelligence CRM",
      logo: null,
      categories: ["crm"],
      auth_schemes: ["OAUTH2"],
      composio_managed: false,
      no_auth: false,
      tools_count: 12,
      triggers_count: 0,
      status: "available",
      integration_id: null,
      set_up: false,
    },
    auth_scheme: "OAUTH2",
    composio_managed: false,
    fields: [
      {
        name: "client_id",
        display_name: "Client id",
        description: "",
        required: true,
        is_secret: false,
      },
      {
        name: "client_secret",
        display_name: "Client secret",
        description: "",
        required: true,
        is_secret: true,
      },
    ],
    ...overrides,
  };
}

function renderDetail() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ComposioToolkitDetail slug="affinity" />
    </QueryClientProvider>,
  );
}

describe("ComposioToolkitDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    enableToolkit.mockResolvedValue({
      integration_id: "affinity",
      auth_config_id: "ac_1",
      origin: "instance",
      composio_managed: false,
    });
  });

  it("enables only once every required field is filled, sending those values", async () => {
    fetchToolkit.mockResolvedValue(detail({}));
    renderDetail();
    const enable = await screen.findByRole("button", { name: /Enable/ });
    expect(enable.hasAttribute("disabled")).toBe(true);

    fireEvent.change(screen.getByLabelText(/Client id/), {
      target: { value: "id-1" },
    });
    fireEvent.change(screen.getByLabelText(/Client secret/), {
      target: { value: "s3" },
    });
    await waitFor(() => expect(enable.hasAttribute("disabled")).toBe(false));
    fireEvent.click(enable);

    await waitFor(() =>
      expect(enableToolkit).toHaveBeenCalledWith("affinity", {
        client_id: "id-1",
        client_secret: "s3",
      }),
    );
  });

  it("offers nothing to enable for an app that needs no sign-in", async () => {
    fetchToolkit.mockResolvedValue(
      detail({
        auth_scheme: null,
        fields: [],
        toolkit: {
          ...detail({}).toolkit,
          no_auth: true,
          status: "unsupported",
        },
      }),
    );
    renderDetail();

    await screen.findByText(/needs no sign-in/);
    expect(
      screen.getByRole("button", { name: /Enable/ }).hasAttribute("disabled"),
    ).toBe(true);
    expect(enableToolkit).not.toHaveBeenCalled();
  });
});
