// @vitest-environment jsdom
/**
 * The composer's readers of the slash-command dropdown's open state (the tools
 * button, the Escape handling of the selected-tool chip) must see it change in
 * the same event that changed it. Fake timers are installed and never advanced,
 * so a reader fed by a polling interval stays stale and fails here. Fidelity:
 * events are dispatched from script in jsdom, not by a real browser.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";

const MATCHES: SlashCommandMatch[] = [
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
];

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

vi.mock("next/navigation", async () => ({
  ...(await vi.importActual<typeof import("next/navigation")>(
    "next/navigation",
  )),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/c",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/chat/hooks/useSlashCommands", () => ({
  useSlashCommands: () => ({
    detectSlashCommand: (text: string) => ({
      isSlashCommand: text.startsWith("/"),
      matches: text.startsWith("/") ? MATCHES : [],
      commandStart: 0,
      commandEnd: text.length,
      query: text.slice(1),
    }),
    getSlashCommandSuggestions: () => MATCHES,
  }),
}));

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations: [], isLoading: false }),
}));

vi.mock("@/features/chat/hooks/useComposerSubmit", async () => {
  const { useComposerStore } = await import("@/stores/composerStore");
  return {
    useComposerSubmit: () => ({
      handleFormSubmit: vi.fn(),
      handleKeyDown: vi.fn(),
      handleRemoveSelectedTool: () =>
        useComposerStore.getState().setSelectedTool(null),
    }),
  };
});

vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({
    selectedWorkflow: null,
    clearSelectedWorkflow: vi.fn(),
  }),
}));
vi.mock("@/features/chat/hooks/useComposerPaste", () => ({
  useComposerPaste: vi.fn(),
}));
vi.mock("@/features/chat/hooks/useComposerSeeds", () => ({
  useComposerSeeds: vi.fn(),
}));
vi.mock("@/features/chat/hooks/useFileAttachments", () => ({
  useFileAttachments: () => ({ attachFiles: vi.fn() }),
}));
vi.mock("@/features/chat/components/composer/ComposerRight", () => ({
  default: () => null,
}));
vi.mock("@/features/chat/components/composer/IntegrationsBanner", () => ({
  default: () => null,
}));

const { default: Composer } = await import(
  "@/features/chat/components/composer/Composer"
);
const { useComposerStore } = await import("@/stores/composerStore");

function renderComposer() {
  render(
    <Composer
      scrollToBottom={vi.fn()}
      inputRef={{ current: null }}
      hasMessages={false}
      voiceModeActive={vi.fn()}
    />,
  );
  return {
    textarea: screen.getByRole("textbox"),
    toolsButton: () =>
      screen
        .getAllByRole("button")
        .find((button) => button.hasAttribute("aria-pressed")),
  };
}

describe("composer slash-command dropdown open state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useComposerStore.setState({
      inputText: "",
      selectedTool: null,
      selectedToolCategory: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the tools button pressed the moment typing '/' opens the dropdown, and released when Escape closes it", () => {
    const { textarea, toolsButton } = renderComposer();
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("false");

    fireEvent.change(textarea, { target: { value: "/" } });
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("true");

    fireEvent.keyDown(textarea, { key: "Escape" });
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("false");
  });

  it("toggles the open state from the tools button with no timer", () => {
    const { toolsButton } = renderComposer();

    fireEvent.click(toolsButton() as HTMLElement);
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(toolsButton() as HTMLElement);
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("false");
  });

  // The textarea's own Escape goes to useComposerSubmit (HeroUI's textarea stops
  // propagation); the chip's window listener covers focus in the dropdown or elsewhere.
  it("keeps the selected tool on the Escape that closes the dropdown, and removes it on the next one", () => {
    act(() => {
      useComposerStore.getState().setSelectedTool("web_search", "search");
    });
    const { textarea, toolsButton } = renderComposer();
    expect(screen.queryByText("Web Search")).not.toBeNull();

    fireEvent.change(textarea, { target: { value: "/" } });
    const dropdown = document.querySelector(".slash-command-dropdown");
    expect(dropdown).not.toBeNull();
    fireEvent.keyDown(dropdown as Element, { key: "Escape" });
    expect(toolsButton()?.getAttribute("aria-pressed")).toBe("false");
    expect(useComposerStore.getState().selectedTool).toBe("web_search");

    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(useComposerStore.getState().selectedTool).toBeNull();
  });
});
