// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const noop = () => undefined;

vi.mock("@/lib/analytics", () => ({
  track: vi.fn(),
}));

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({
    userEmail: "test@example.com",
    isAuthenticated: true,
    openLoginModal: vi.fn(),
  }),
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/c/test",
  useRouter: () => ({ push: vi.fn() }),
}));

// jsdom geometry makes the real virtualizer compute an empty item range, so
// pin the measurement plumbing and render every row deterministically.
vi.mock("@tanstack/react-virtual", async () => {
  const actual = await vi.importActual<
    typeof import("@tanstack/react-virtual")
  >("@tanstack/react-virtual");
  return {
    ...actual,
    useVirtualizer: (options: {
      count: number;
      estimateSize: (index: number) => number;
    }) => {
      const count = options.count ?? 0;
      const items = Array.from({ length: count }, (_, index) => ({
        index,
        key: String(index),
        start: index * 48,
        end: (index + 1) * 48,
        size: 48,
        lane: 0,
      }));
      return {
        getVirtualItems: () => items,
        getTotalSize: () => count * 48,
        measureElement: () => undefined,
        scrollToIndex: () => undefined,
        scrollToOffset: () => undefined,
        measure: () => undefined,
        resizeItem: () => undefined,
      };
    },
  };
});

vi.mock("@/features/integrations/api/integrationsApi", () => {
  const getMyIntegrations = vi.fn(async () => ({
    integrations: [
      {
        id: "github",
        name: "GitHub",
        description: "Code hosting",
        category: "developer",
        source: "platform",
        managedBy: "composio",
        status: "connected",
        requiresAuth: true,
        authType: "oauth",
        isFeatured: false,
        displayPriority: 1,
        available: true,
        toolCount: 3,
        cloneCount: 0,
        creator: null,
      },
      {
        id: "notion",
        name: "Notion",
        description: "Notes and docs",
        category: "productivity",
        source: "platform",
        managedBy: "composio",
        status: "created",
        requiresAuth: true,
        authType: "oauth",
        isFeatured: false,
        displayPriority: 1,
        available: true,
        toolCount: 2,
        cloneCount: 0,
        creator: null,
      },
      {
        id: "gmailcalendar",
        name: "Gmail / Calendar",
        description: "Email and calendar",
        category: "productivity",
        source: "platform",
        managedBy: "composio",
        status: "expired",
        expiredAt: "2026-08-01T00:00:00Z",
        requiresAuth: true,
        authType: "oauth",
        isFeatured: false,
        displayPriority: 1,
        available: true,
        toolCount: 4,
        cloneCount: 0,
        creator: null,
      },
    ],
    total: 3,
  }));

  return {
    integrationsApi: {
      getMyIntegrations,
      getMyIntegrationsSnapshot: getMyIntegrations,
      getIntegrationStatuses: vi.fn(async () => ({ statuses: {} })),
    },
  };
});

import { toolIconConfigs } from "@/config/toolIconConfig";
import { LockedCategorySection } from "@/features/chat/components/composer/LockedCategorySection";
import SlashCommandDropdown from "@/features/chat/components/composer/SlashCommandDropdown";
import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";
import { formatToolName } from "@/features/chat/utils/chatUtils";

class ResizeObserverStub implements ResizeObserver {
  private readonly cb: ResizeObserverCallback;

  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }

  observe(el: Element) {
    this.cb(
      [
        {
          target: el,
          contentRect: {
            x: 0,
            y: 0,
            width: 800,
            height: 600,
            top: 0,
            left: 0,
            bottom: 600,
            right: 800,
          } as DOMRectReadOnly,
        } as ResizeObserverEntry,
      ],
      this,
    );
  }

  unobserve() {
    // No dynamic resize in tests.
  }

  disconnect() {
    // Nothing to clean up.
  }
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  Element.prototype.scrollIntoView = vi.fn();
  // jsdom reports zero-size rects, which makes the row virtualizer compute an
  // empty item range. Report a realistic viewport instead.
  Element.prototype.getBoundingClientRect = () =>
    ({
      x: 0,
      y: 0,
      width: 800,
      height: 600,
      top: 0,
      left: 0,
      bottom: 600,
      right: 800,
      toJSON: () => ({}),
    }) as DOMRect;
});

const matches: SlashCommandMatch[] = [
  {
    tool: {
      name: "web_search",
      category: "search",
      display_name: "Web Search",
      icon_url: null,
      requires_integration: false,
      locked: false,
    },
    matchedText: "/web_search",
  },
  {
    tool: {
      name: "create_note",
      category: "notion",
      display_name: "Notion",
      icon_url: null,
      requires_integration: true,
      locked: true,
    },
    enhancedTool: {
      name: "create_note",
      category: "notion",
      displayName: "Notion",
      isLocked: true,
    },
    matchedText: "/create_note",
  },
];

function withProviders(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("composer tools dropdown DOM health", () => {
  it("renders every dropdown row type without nesting a button inside a button", async () => {
    withProviders(
      <SlashCommandDropdown
        matches={matches}
        selectedIndex={0}
        onSelect={noop}
        onClose={noop}
        position={{ left: 0 }}
        isVisible
        openedViaButton
      />,
    );

    // Every row type actually mounted before asserting on the tree shape.
    expect((await screen.findAllByText("Web Search")).length).toBeGreaterThan(
      0,
    ); // unlocked tool row
    await screen.findByText("Integrations"); // integrations card accordion
    expect((await screen.findAllByText("Create Note")).length).toBeGreaterThan(
      0,
    ); // locked tool row
    // Locked category header action (name includes the leading icon).
    expect(
      (await screen.findAllByRole("button", { name: /connect/i })).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByRole("button").length).toBeGreaterThan(3);

    // validateDOMNesting guard: no <button> may descend from another <button>.
    // The dropdown portals to <body>, so query the document, not the container.
    expect(document.querySelector("button button")).toBeNull();
  });

  it("locked category section renders without nesting buttons", async () => {
    const { container } = withProviders(
      <LockedCategorySection
        category="notion"
        tools={[matches[1] as SlashCommandMatch]}
        requiredIntegration={{ id: "notion", name: "Notion" }}
        onConnect={noop}
      />,
    );

    await screen.findByText(/tools locked/);
    expect(container.querySelector("button button")).toBeNull();
  });
});

// A locked tool ahead of two unlocked ones: the ordering that separates the
// full-match index space from the unlocked-row one selectedIndex actually uses.
const lockedFirstMatches: SlashCommandMatch[] = [
  matches[1] as SlashCommandMatch,
  matches[0] as SlashCommandMatch,
  {
    tool: {
      name: "deep_research",
      category: "search",
      display_name: "Deep Research",
      icon_url: null,
      requires_integration: false,
      locked: false,
    },
    matchedText: "/deep_research",
  },
];

describe("dropdown keyboard activation", () => {
  it("activates the highlighted unlocked row, not the same position in the full list", async () => {
    const onSelect = vi.fn();
    withProviders(
      <SlashCommandDropdown
        matches={lockedFirstMatches}
        // Second UNLOCKED row = Deep Research. Full-list index 1 is Web Search,
        // which is what the dropdown's old private key handler picked.
        selectedIndex={1}
        onSelect={onSelect}
        onClose={noop}
        position={{ left: 0 }}
        isVisible
        openedViaButton
      />,
    );
    await screen.findByText("Deep Research");

    const dropdown = document.querySelector(".slash-command-dropdown");
    expect(dropdown).not.toBeNull();
    fireEvent.keyDown(dropdown as Element, { key: "Enter" });

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        tool: expect.objectContaining({ name: "deep_research" }),
      }),
    );
  });

  it("never activates a locked row", async () => {
    const onSelect = vi.fn();
    withProviders(
      <SlashCommandDropdown
        matches={lockedFirstMatches}
        selectedIndex={0}
        onSelect={onSelect}
        onClose={noop}
        position={{ left: 0 }}
        isVisible
        openedViaButton
      />,
    );
    await screen.findByText("Deep Research");

    fireEvent.keyDown(
      document.querySelector(".slash-command-dropdown") as Element,
      { key: "Enter" },
    );

    // Index 0 of the unlocked list is Web Search; the locked Notion row sits at
    // full-list index 0 and must be unreachable from the keyboard.
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        tool: expect.objectContaining({ name: "web_search" }),
      }),
    );
  });
});

// Registry categories with no entry in toolIconConfigs (apps/api registry.py).
const UNCONFIGURED_REGISTRY_CATEGORIES = ["control", "execute", "instructions"];
const CUSTOM_LOGO_URL = "https://example.com/acme-logo.png";

function iconCategoryMatch(
  category: string,
  iconUrl: string | null = null,
): SlashCommandMatch {
  return {
    tool: {
      name: `probe_${category}`,
      category,
      display_name: `tab ${category}`,
      icon_url: iconUrl,
      requires_integration: false,
      locked: false,
    },
    matchedText: `/probe_${category}`,
  };
}

/** What a rendered icon shows: the image's source, or the glyph's path data. */
function iconSignature(scope: Element): string {
  const img = scope.querySelector("img");
  if (img) {
    const src = img.getAttribute("src") ?? "";
    return new URL(src, "http://local").searchParams.get("url") ?? src;
  }
  return scope.querySelector("svg")?.innerHTML ?? "";
}

describe("slash menu icons", () => {
  const categories = [
    ...Object.keys(toolIconConfigs),
    ...UNCONFIGURED_REGISTRY_CATEGORIES,
    "browser",
    "acme_mcp_no_logo",
  ];
  const iconMatches = [
    ...categories.map((category) => iconCategoryMatch(category)),
    iconCategoryMatch("acme_mcp_with_logo", CUSTOM_LOGO_URL),
  ];

  it.each([...categories, "acme_mcp_with_logo"])(
    "shows the same %s icon on the tab and on its tool row, loaded eagerly",
    async (category) => {
      withProviders(
        <SlashCommandDropdown
          matches={iconMatches}
          selectedIndex={0}
          onSelect={noop}
          onClose={noop}
          position={{ left: 0 }}
          isVisible
          openedViaButton
        />,
      );
      const toolLabel = formatToolName(`probe_${category}`);
      const row = (await screen.findByText(toolLabel)).closest("button");
      const tab = screen
        .getAllByText(`tab ${category}`)
        .map((label) => label.closest("button"))
        .find(
          (button) =>
            button !== row && !button?.textContent?.includes(toolLabel),
        );

      expect(row).not.toBeNull();
      expect(tab).toBeTruthy();
      const rowIcon = iconSignature(row as Element);
      expect(rowIcon).not.toBe("");
      expect(iconSignature(tab as Element)).toBe(rowIcon);
      // Tabs sit in a horizontal scroller: a lazy logo past its clipped edge is never fetched.
      for (const img of (tab as Element).querySelectorAll("img")) {
        expect(img.getAttribute("loading")).toBe("eager");
      }
      if (category === "acme_mcp_with_logo") {
        expect(rowIcon).toBe(CUSTOM_LOGO_URL);
      }
    },
  );
});

describe("slash menu category names", () => {
  it("shows the integration's own name on the tab and the row chip, as the sidebar does", async () => {
    withProviders(
      <SlashCommandDropdown
        matches={[
          {
            tool: {
              name: "list_pull_requests",
              category: "github",
              display_name: "GitHub",
              icon_url: null,
              requires_integration: true,
              locked: false,
            },
            matchedText: "/list_pull_requests",
          },
        ]}
        selectedIndex={0}
        onSelect={noop}
        onClose={noop}
        position={{ left: 0 }}
        isVisible
        openedViaButton
      />,
    );
    await screen.findByText("List Pull Requests");

    expect(screen.getAllByText("GitHub")).toHaveLength(2);
    expect(screen.queryByText("Github")).toBeNull();
  });
});

describe("dropdown layering", () => {
  it("mounts at the document root, outside the composer's stacking context", async () => {
    withProviders(
      // The composer's searchbar is `relative z-2`: anything inside it is
      // capped at that layer no matter its own z-index.
      <div data-testid="composer-searchbar" className="relative z-2">
        <SlashCommandDropdown
          matches={matches}
          selectedIndex={0}
          onSelect={noop}
          onClose={noop}
          position={{ left: 0 }}
          isVisible
          openedViaButton
        />
      </div>,
    );
    await screen.findAllByText("Web Search");

    const dropdown = document.querySelector(".slash-command-dropdown");
    expect(dropdown).not.toBeNull();
    expect(screen.getByTestId("composer-searchbar").contains(dropdown)).toBe(
      false,
    );
    expect(dropdown?.parentElement).toBe(document.body);
  });
});

describe("integrations card row actions", () => {
  it("offers Retry for a pending integration, Reconnect for expired, nothing to redo connected", async () => {
    const { IntegrationsCard } = await import(
      "@/features/integrations/components/IntegrationsCard"
    );
    const { container } = withProviders(<IntegrationsCard />);

    await screen.findByText("Notion");

    // Pending ("created") rows must surface the retry action like siblings do.
    const notionRow = screen
      .getByText("Notion")
      .closest(".min-h-12") as HTMLElement;
    expect(
      within(notionRow).getByRole("button", { name: "Retry" }),
    ).toBeTruthy();

    const gmailRow = screen
      .getByText("Gmail / Calendar")
      .closest(".min-h-12") as HTMLElement;
    expect(
      within(gmailRow).getByRole("button", { name: "Reconnect" }),
    ).toBeTruthy();

    const githubRow = screen
      .getByText("GitHub")
      .closest(".min-h-12") as HTMLElement;
    // Connected rows keep their clickable-name button but no action button.
    expect(
      within(githubRow).queryByRole("button", {
        name: /^(connect|retry|reconnect)$/i,
      }),
    ).toBeNull();

    expect(container.querySelector("button button")).toBeNull();
  });
});
