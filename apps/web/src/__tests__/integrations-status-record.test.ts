/**
 * The derivations `useIntegrations` hands every non-integrations-page surface.
 *
 * `getIntegrationStatus` used to return only `{integrationId, connected}`, so
 * the dashboard/settings/calendar CTAs rendered a first-time "Connect" for an
 * integration the user had already connected and which then broke. It now
 * carries the raw `status`, which is what lets those surfaces run it through
 * `integrationConnectionState` + `CONNECT_ACTION_LABEL` and say "Reconnect".
 * The catalog mapping likewise carries `expiredAt`, which the integrations row
 * renders as "Disconnected <n> ago".
 *
 * Fidelity note: this workspace has no jsdom/happy-dom and no
 * `@testing-library/react`, so there is no renderer and `renderHook` is
 * unavailable. `useCallback`/`useMemo`/`useRef` are stubbed with the minimum
 * semantics the hook relies on and the hook body is invoked directly. What runs
 * for real: the catalog mapping, the sort, and the status lookup. What is NOT
 * exercised: React's memo/dependency scheduling, and no component rendering at
 * all — that the row actually paints "Disconnected 3 days ago", or that the
 * dashboard button paints "Reconnect", is unverified here.
 */
import type { MyIntegrationItem, MyIntegrationsResponse } from "@shared/types";
import {
  CONNECT_ACTION_LABEL,
  integrationConnectionState,
} from "@shared/utils";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

const harness = vi.hoisted(() => ({
  data: null as { integrations: unknown[] } | null,
  queryClient: null as import("@tanstack/react-query").QueryClient | null,
}));

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useCallback: <T>(fn: T): T => fn,
    useMemo: <T>(fn: () => T): T => fn(),
    useRef: <T>(initial: T): { current: T } => ({ current: initial }),
  };
});

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: () => ({ data: harness.data, isLoading: false, error: null }),
    useMutation: () => ({ mutateAsync: vi.fn() }),
    useQueryClient: () => {
      if (!harness.queryClient) throw new Error("queryClient not installed");
      return harness.queryClient;
    },
  };
});

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({
    userEmail: "dev@gaia.local",
    isAuthenticated: true,
    openLoginModal: vi.fn(),
  }),
}));

function item(overrides: Partial<MyIntegrationItem>): MyIntegrationItem {
  return {
    id: "gmail",
    name: "Gmail",
    description: "Email",
    category: "communication",
    source: "platform",
    managedBy: "composio",
    status: "not_connected",
    requiresAuth: true,
    isFeatured: true,
    displayPriority: 0,
    available: true,
    toolCount: 3,
    cloneCount: 0,
    ...overrides,
  };
}

function install(...items: MyIntegrationItem[]): void {
  harness.data = { integrations: items } satisfies Pick<
    MyIntegrationsResponse,
    "integrations"
  >;
}

/** Invokes the hook body outside React — see the fidelity note above. */
function callHook(): ReturnType<typeof useIntegrations> {
  // biome-ignore lint/correctness/useHookAtTopLevel: no DOM renderer exists in this workspace, so this driver invokes the hook body outside React on purpose.
  return useIntegrations();
}

describe("useIntegrations.getIntegrationStatus", () => {
  beforeEach(() => {
    harness.queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("carries the backend status, not just the connected boolean", () => {
    install(item({ status: "expired" }));

    const record = callHook().getIntegrationStatus("gmail");

    expect(record).toEqual({
      integrationId: "gmail",
      connected: false,
      status: "expired",
    });
  });

  it("lets a caller label a dead connection Reconnect instead of Connect", () => {
    install(item({ status: "expired" }), item({ id: "slack", name: "Slack" }));

    const { getIntegrationStatus } = callHook();
    const label = (id: string) =>
      CONNECT_ACTION_LABEL[
        integrationConnectionState(getIntegrationStatus(id)?.status)
      ];

    expect(label("gmail")).toBe("Reconnect");
    expect(label("slack")).toBe("Connect");
  });

  it("labels an added-but-never-authenticated integration Retry", () => {
    install(item({ status: "created" }));

    expect(
      CONNECT_ACTION_LABEL[
        integrationConnectionState(
          callHook().getIntegrationStatus("gmail")?.status,
        )
      ],
    ).toBe("Retry");
  });

  it("matches the integration id case-insensitively", () => {
    install(item({ id: "GoogleCalendar", status: "connected" }));

    const record = callHook().getIntegrationStatus("googlecalendar");

    expect(record?.status).toBe("connected");
    expect(record?.connected).toBe(true);
  });

  it("returns undefined for an integration missing from the catalog", () => {
    install(item({}));

    expect(callHook().getIntegrationStatus("notion")).toBeUndefined();
  });
});

describe("useIntegrations catalog mapping", () => {
  beforeEach(() => {
    harness.queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("carries expiredAt through so the row can say when the grant died", () => {
    install(item({ status: "expired", expiredAt: "2026-08-15T09:00:00Z" }));

    expect(callHook().integrations[0].expiredAt).toBe("2026-08-15T09:00:00Z");
  });

  it("normalizes a null expiredAt to undefined", () => {
    install(item({ status: "connected", expiredAt: null }));

    expect(callHook().integrations[0].expiredAt).toBeUndefined();
  });
});
