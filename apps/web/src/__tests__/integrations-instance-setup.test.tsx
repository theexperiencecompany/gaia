// @vitest-environment jsdom
/** The integrations page says what is missing on this instance in place, with the fix, never in a passing toast. */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const user = { role: "admin" as "admin" | "member" };
const instance = { composioKey: false };
const catalogPage = {
  composio_configured: true,
  items: [],
  total: 0,
  categories: [],
};

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ role: user.role }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({
    data: {
      providers: {
        composio: {
          configured: instance.composioKey,
          env_shadowed: false,
          source: instance.composioKey ? "stored" : "unset",
        },
      },
    },
  }),
  useDeployment: () => ({ instance_toolkits: true }),
}));
vi.mock("@/features/settings/hooks/useComposioToolkits", () => ({
  useComposioCatalog: () => ({
    data: { pages: [catalogPage] },
    isLoading: false,
    error: null,
    hasNextPage: false,
  }),
}));

import { InstanceSetupCallout } from "@/features/integrations/components/InstanceSetupNotice";
import { IntegrationsBanner } from "@/features/integrations/components/IntegrationsBanner";
import { ComposioCatalogModal } from "@/features/settings/components/composio/ComposioCatalogModal";

const SETUP_PATH = "/settings/integrations-setup";

/** Where an action labelled `name` goes; HeroUI renders link buttons as anchors with role="button". */
const linkTo = (name: RegExp) =>
  screen.getByText(name).closest("a")?.getAttribute("href");

describe("the integrations banner", () => {
  beforeEach(() => {
    user.role = "admin";
    instance.composioKey = false;
  });

  it("leads an admin without a Composio key to add one, with the other ways in as secondary", () => {
    render(<IntegrationsBanner onAddMcpServer={vi.fn()} />);

    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(linkTo(/add composio key/i)).toBe(SETUP_PATH);
    expect(
      screen.getByRole("button", { name: /add mcp server/i }),
    ).toBeTruthy();
    expect(linkTo(/^marketplace$/i)).toBe("/marketplace");
  });

  it("opens the catalog for an admin whose instance has a key", () => {
    instance.composioKey = true;
    render(<IntegrationsBanner onAddMcpServer={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: /browse 1,600\+ apps/i }),
    ).toBeTruthy();
    expect(screen.queryByText(/add composio key/i)).toBeNull();
  });

  it("offers a member the Marketplace, not instance setup", () => {
    user.role = "member";
    render(<IntegrationsBanner onAddMcpServer={vi.fn()} />);

    expect(linkTo(/browse marketplace/i)).toBe("/marketplace");
    expect(screen.queryByText(/composio/i)).toBeNull();
  });
});

describe("an integration not set up on this instance", () => {
  it("shows the admin the fix in place", () => {
    user.role = "admin";
    render(<InstanceSetupCallout name="Gmail" />);

    expect(
      screen.getByText("Gmail isn't set up on this instance"),
    ).toBeTruthy();
    expect(linkTo(/set it up/i)).toBe(SETUP_PATH);
  });

  it("tells a member who can fix it", () => {
    user.role = "member";
    render(<InstanceSetupCallout name="Gmail" />);

    expect(screen.getByText(/ask this instance's admin/i)).toBeTruthy();
    expect(document.querySelector("a")).toBeNull();
  });
});

describe("the Composio catalog without a key", () => {
  it("asks for the key instead of showing an error or an empty search", () => {
    catalogPage.composio_configured = false;
    render(<ComposioCatalogModal isOpen onClose={vi.fn()} />);

    expect(
      screen.getByText("Add a Composio key to browse 1,600+ apps"),
    ).toBeTruthy();
    expect(linkTo(/add composio key/i)).toBe(SETUP_PATH);
    expect(screen.queryByText(/no app matches/i)).toBeNull();
  });
});
