// @vitest-environment jsdom
/** The home setup banner: one line per missing item, collapsed when several, dismissal re-arms. */

import { fireEvent, render, screen } from "@testing-library/react";
import { domAnimation, LazyMotion } from "motion/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

const state: { status: SetupStatus; role: string | undefined } = {
  status: {} as SetupStatus,
  role: "admin",
};

const CATALOG = {
  providers: {},
  custom_presets: {},
  llm_provider_keys: ["openai"],
} as unknown as ProviderCatalog;

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: state.role }),
}));
vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({ data: CATALOG }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({ data: state.status }),
}));

import { SetupChecklistBanner } from "@/features/setup-wizard/components/SetupChecklistBanner";
import { useSetupChecklistStore } from "@/stores/setupChecklistStore";

const PERSIST_KEY = "gaia-setup-checklist";

function dismissedBefore(keys: string[]): void {
  useSetupChecklistStore.setState({ dismissedKeys: keys });
}

function persistedDismissedKeys(): unknown {
  const raw = window.localStorage.getItem(PERSIST_KEY) ?? "{}";
  return JSON.parse(raw).state?.dismissedKeys;
}

/** Providers in configured are set up; "web_search" there means search works. */
function statusWith(configured: string[], hasAdmin: boolean): SetupStatus {
  return {
    auth_mode: "local",
    has_admin_account: hasAdmin,
    providers: Object.fromEntries(
      configured.map((key) => [key, { configured: true }]),
    ),
    features: {
      web_search: { working: configured.includes("web_search"), in_use: [] },
    },
  } as unknown as SetupStatus;
}

function renderBanner(): void {
  const wrap = ({ children }: { children: ReactNode }) => (
    <LazyMotion features={domAnimation}>{children}</LazyMotion>
  );
  render(<SetupChecklistBanner />, { wrapper: wrap });
}

beforeEach(() => {
  window.localStorage.clear();
  dismissedBefore([]);
  state.role = "admin";
});
afterEach(() => vi.clearAllMocks());

describe("SetupChecklistBanner", () => {
  it("renders nothing once every essential is configured", () => {
    state.status = statusWith(["openai", "web_search"], true);
    renderBanner();
    expect(screen.queryByLabelText("Dismiss setup checklist")).toBeNull();
  });

  it("shows a single missing item as one line with its action", () => {
    state.status = statusWith(["openai"], true);
    renderBanner();

    expect(screen.getByText("Enable web search")).toBeTruthy();
    const action = screen.getByRole("button", { name: "Enable" });
    expect(action.getAttribute("href")).toBe("/settings/providers");
    expect(screen.queryByText(/setup steps left/)).toBeNull();
  });

  it("collapses several items into one line that expands to a row each", () => {
    state.status = statusWith([], false);
    renderBanner();

    expect(screen.getByText("3 setup steps left")).toBeTruthy();
    expect(screen.queryByText("Connect an AI provider")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const hrefs = ["Connect", "Enable", "Create"].map((name) =>
      screen.getByRole("button", { name }).getAttribute("href"),
    );
    expect(hrefs).toEqual(["/setup", "/settings/providers", "/signup"]);
    expect(screen.getByText("Create the admin account")).toBeTruthy();
  });

  it("persists a dismissal of exactly the pending items and hides", () => {
    state.status = statusWith(["openai"], false);
    renderBanner();

    fireEvent.click(screen.getByLabelText("Dismiss setup checklist"));

    expect(screen.queryByText(/setup steps left/)).toBeNull();
    expect(persistedDismissedKeys()).toEqual(["search", "admin"]);
  });

  it("re-arms when an item returns after a dismissal", () => {
    dismissedBefore(["search"]);
    state.status = statusWith([], true);
    renderBanner();

    expect(screen.getByText("2 setup steps left")).toBeTruthy();
  });

  it("re-arms when the pending set shrinks after a dismissal", () => {
    dismissedBefore(["search", "admin"]);
    state.status = statusWith(["openai"], true);
    renderBanner();

    expect(screen.getByText("Enable web search")).toBeTruthy();
  });

  it("stays hidden while the dismissed set still matches", () => {
    dismissedBefore(["search"]);
    state.status = statusWith(["openai"], true);
    renderBanner();

    expect(screen.queryByText("Enable web search")).toBeNull();
  });

  it("is never shown to a member", () => {
    state.role = "member";
    state.status = statusWith([], false);
    renderBanner();

    expect(screen.queryByText("3 setup steps left")).toBeNull();
  });

  it("stays hidden while the role is still loading", () => {
    state.role = undefined;
    state.status = statusWith([], false);
    renderBanner();

    expect(screen.queryByText("3 setup steps left")).toBeNull();
  });
});
