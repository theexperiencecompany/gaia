// @vitest-environment jsdom
/**
 * A connect the user makes refreshes the integration and tool caches from its
 * own success path, so it never depends on the status broadcast's socket being
 * up. Fidelity: the API and the bearer modal are stubbed; each site's success
 * handler runs for real and the helper is observed, not the refetch it starts.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  Integration,
  PublicIntegrationResponse,
  SuggestedIntegration,
} from "@/features/integrations/types";

const harness = vi.hoisted(() => ({
  invalidateIntegrationCaches: vi.fn(),
  bearerOptions: [] as Array<{
    onConnected: (
      id: string,
      result: { status: string; name?: string },
    ) => void;
  }>,
}));

vi.mock("@/features/integrations/api/queryKeys", async (importActual) => ({
  ...(await importActual<
    typeof import("@/features/integrations/api/queryKeys")
  >()),
  invalidateIntegrationCaches: harness.invalidateIntegrationCaches,
}));

vi.mock("@/features/integrations/api/integrationsApi", () => ({
  integrationsApi: {
    connectIntegration: vi.fn(async () => ({
      status: "connected",
      name: "DeepWiki",
    })),
    addIntegration: vi.fn(async () => ({
      status: "connected",
      name: "DeepWiki",
    })),
    getMyIntegrationsSnapshot: vi.fn(async () => ({ integrations: [] })),
    getIntegrationStatuses: vi.fn(async () => ({ statuses: {} })),
  },
}));

vi.mock("@/features/integrations/hooks/useBearerTokenModal", () => ({
  useBearerTokenModal: (options: (typeof harness.bearerOptions)[number]) => {
    harness.bearerOptions.push(options);
    return {
      isOpen: false,
      integrationId: "",
      integrationName: "",
      open: vi.fn(),
      close: vi.fn(),
      submit: vi.fn(),
    };
  },
}));

vi.mock("@/features/integrations/components/BearerTokenModal", () => ({
  BearerTokenModal: () => null,
}));

vi.mock("@/lib/toast", () => ({
  toast: Object.assign(vi.fn(), {
    loading: vi.fn(() => "toast-id"),
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    dismiss: vi.fn(),
  }),
}));

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true, openLoginModal: vi.fn() }),
}));

vi.mock("next/navigation", async (importActual) => ({
  ...(await importActual<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/hooks/layout/useHeader", () => ({
  useHeader: () => ({ setHeader: vi.fn() }),
}));
vi.mock("@/hooks/ui/usePlatform", () => ({
  usePlatform: () => ({ isMac: false }),
}));
vi.mock("@/features/integrations/hooks/useIntegrationDeepLink", () => ({
  useIntegrationDeepLink: vi.fn(),
}));
vi.mock("@/features/integrations/components/IntegrationsList", () => ({
  IntegrationsList: () => null,
}));
vi.mock("@/features/integrations/components/IntegrationsSearchInput", () => ({
  IntegrationsSearchInput: () => null,
}));
vi.mock("@/features/support/components/ContactSupportModal", () => ({
  default: () => null,
}));

const { default: IntegrationsPage } = await import(
  "@/app/[locale]/(main)/integrations/page"
);
const { useIntegrations } = await import(
  "@/features/integrations/hooks/useIntegrations"
);
const { useAddIntegration } = await import(
  "@/app/[locale]/(landing)/marketplace/[slug]/useAddIntegration"
);
const { IntegrationActions } = await import(
  "@/components/layout/sidebar/right-variants/integration-sidebar/IntegrationActions"
);
const { IntegrationListSection } = await import(
  "@/features/integrations/components/IntegrationListSection"
);

function withQueryClient({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

const lastBearerOptions = () => harness.bearerOptions.at(-1);

describe("a connect the user makes refreshes the integration caches", () => {
  beforeEach(() => {
    harness.invalidateIntegrationCaches.mockClear();
    harness.bearerOptions.length = 0;
  });

  it("connectIntegration, when the response says connected", async () => {
    const { result } = renderHook(() => useIntegrations(), {
      wrapper: withQueryClient,
    });

    await act(() => result.current.connectIntegration("deepwiki"));

    expect(harness.invalidateIntegrationCaches).toHaveBeenCalledTimes(1);
  });

  it("the marketplace bearer modal's success", () => {
    renderHook(
      () =>
        useAddIntegration({
          integrationId: "deepwiki",
          name: "DeepWiki",
          source: "custom",
        } as PublicIntegrationResponse),
      { wrapper: withQueryClient },
    );

    act(() =>
      lastBearerOptions()?.onConnected("deepwiki", { status: "connected" }),
    );

    expect(harness.invalidateIntegrationCaches).toHaveBeenCalledTimes(1);
  });

  it("the integrations page's bearer modal success", () => {
    render(<IntegrationsPage />, { wrapper: withQueryClient });

    act(() =>
      lastBearerOptions()?.onConnected("deepwiki", {
        status: "connected",
        name: "DeepWiki",
      }),
    );

    expect(harness.invalidateIntegrationCaches).toHaveBeenCalledTimes(1);
  });

  it("the integration sidebar's bearer modal success", () => {
    render(
      <IntegrationActions
        integration={
          { id: "deepwiki", name: "DeepWiki", status: "created" } as Integration
        }
        isConnected={false}
        onConnect={vi.fn()}
      />,
      { wrapper: withQueryClient },
    );

    act(() =>
      lastBearerOptions()?.onConnected("deepwiki", { status: "connected" }),
    );

    expect(harness.invalidateIntegrationCaches).toHaveBeenCalledTimes(1);
  });

  it("adding a suggested integration", async () => {
    const suggestion: SuggestedIntegration = {
      id: "deepwiki",
      name: "DeepWiki",
      description: "Docs for any repo",
      category: "developer",
      relevanceScore: 1,
      slug: "deepwiki",
    };
    render(<IntegrationListSection suggestedIntegrations={[suggestion]} />, {
      wrapper: withQueryClient,
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });

    expect(harness.invalidateIntegrationCaches).toHaveBeenCalledTimes(1);
  });
});
