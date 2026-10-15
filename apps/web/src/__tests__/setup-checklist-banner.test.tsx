// @vitest-environment jsdom
/** The home setup banner: what is left to configure, required first, each item dismissable on its own. */

import type { FeatureSpec } from "@gaia/shared/api/generated";
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

const feature = (
  label: string,
  builtIn: FeatureSpec["built_in"] = null,
): FeatureSpec => ({
  label,
  description: `${label} description.`,
  built_in: builtIn,
  providers: [],
});

const CATALOG = {
  providers: {},
  custom_presets: {},
  llm_provider_keys: ["openai"],
  features: {
    ai_models: feature("AI models"),
    web_search: feature("Web search", {
      engine: "duckduckgo",
      label: "DuckDuckGo",
      description: "Free, no key needed.",
    }),
    email: feature("Email"),
    integrations: feature("Integrations"),
    browser: feature("Browser"),
  },
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

/** Providers in configured are set up; features in working work. Web search is always off, which must not matter. */
function statusWith(
  configured: string[],
  hasAdmin: boolean,
  working: string[] = ["email", "integrations"],
): SetupStatus {
  const off = { working: false, available: true, in_use: [] };
  const on = { working: true, available: true, in_use: [] };
  return {
    auth_mode: "local",
    has_admin_account: hasAdmin,
    providers: Object.fromEntries(
      configured.map((key) => [key, { configured: true }]),
    ),
    features: {
      ai_models: configured.includes("openai") ? on : off,
      web_search: off,
      email: working.includes("email") ? on : off,
      integrations: working.includes("integrations") ? on : off,
      browser: { working: false, available: false, in_use: [] },
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
  it("renders nothing once every essential and feature is configured", () => {
    state.status = statusWith(["openai"], true);
    renderBanner();
    expect(screen.queryByLabelText("Dismiss setup checklist")).toBeNull();
  });

  it("never lists a feature that runs on a free built-in", () => {
    state.status = statusWith(["openai"], true);
    renderBanner();

    expect(screen.queryByText("Web search")).toBeNull();
  });

  it("never lists a feature this instance cannot run", () => {
    state.status = statusWith(["openai"], true);
    renderBanner();

    expect(screen.queryByText("Browser")).toBeNull();
  });

  it("shows a single missing item as one line with its action", () => {
    state.status = statusWith(["openai"], false);
    renderBanner();

    expect(screen.getByText("Create the admin account")).toBeTruthy();
    const action = screen.getByRole("button", { name: "Create" });
    expect(action.getAttribute("href")).toBe("/signup");
    expect(screen.queryByText(/setup steps left/)).toBeNull();
  });

  it("lists required items first, then each optional feature that is off, linked to its Settings card", () => {
    state.status = statusWith([], false, ["integrations"]);
    renderBanner();

    expect(screen.getByText("3 setup steps left")).toBeTruthy();
    expect(screen.queryByText("Connect an AI provider")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    const hrefs = ["Connect", "Create", "Set up"].map((name) =>
      screen.getByRole("button", { name }).getAttribute("href"),
    );
    expect(hrefs).toEqual([
      "/setup",
      "/signup",
      "/settings/providers?feature=email",
    ]);
    expect(screen.getByText("Email")).toBeTruthy();
    expect(screen.queryByText("AI models")).toBeNull();
  });

  it("dismisses one item and keeps the rest", () => {
    state.status = statusWith(["openai"], false, []);
    renderBanner();
    fireEvent.click(screen.getByRole("button", { name: "Show" }));

    fireEvent.click(screen.getByLabelText("Dismiss Email"));

    expect(screen.getByText("2 setup steps left")).toBeTruthy();
    expect(screen.queryByText("Email")).toBeNull();
    expect(persistedDismissedKeys()).toEqual(["email"]);
  });

  it("dismisses every shown item at once and hides", () => {
    state.status = statusWith([], false);
    renderBanner();

    fireEvent.click(screen.getByLabelText("Dismiss setup checklist"));

    expect(screen.queryByText(/setup steps left/)).toBeNull();
    expect(persistedDismissedKeys()).toEqual(["llm", "admin"]);
  });

  it("stays hidden while a dismissed item is still pending", () => {
    dismissedBefore(["admin"]);
    state.status = statusWith(["openai"], false);
    renderBanner();

    expect(screen.queryByText("Create the admin account")).toBeNull();
  });

  it("forgets a dismissal once its item is done, so a return shows it again", () => {
    dismissedBefore(["llm", "admin"]);
    state.status = statusWith(["openai"], false);
    renderBanner();

    expect(persistedDismissedKeys()).toEqual(["admin"]);
  });

  it("is never shown to a member", () => {
    state.role = "member";
    state.status = statusWith([], false);
    renderBanner();

    expect(screen.queryByText("2 setup steps left")).toBeNull();
  });

  it("stays hidden while the role is still loading", () => {
    state.role = undefined;
    state.status = statusWith([], false);
    renderBanner();

    expect(screen.queryByText("2 setup steps left")).toBeNull();
  });
});
