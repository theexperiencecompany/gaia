// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { describe, expect, it, vi } from "vitest";

import type { SlashCommandMatch } from "@/features/chat/hooks/useSlashCommands";

// The dropdown renders locked tools alongside unlocked ones, and a locked tool
// can sort ahead of the unlocked ones. That ordering is what separates the
// full-list index space from the unlocked-row one, so it is the fixture.
const LOCKED_FIRST_MATCHES: SlashCommandMatch[] = [
  {
    tool: {
      name: "create_note",
      category: "notion",
      display_name: "Notion",
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
  {
    tool: {
      name: "web_search",
      category: "search",
      display_name: "Web Search",
      requires_integration: false,
      locked: false,
    },
    matchedText: "/web_search",
  },
  {
    tool: {
      name: "deep_research",
      category: "search",
      display_name: "Deep Research",
      requires_integration: false,
      locked: false,
    },
    matchedText: "/deep_research",
  },
];

vi.mock("@/features/chat/hooks/useSlashCommands", () => ({
  useSlashCommands: () => ({
    detectSlashCommand: () => ({
      isSlashCommand: true,
      matches: LOCKED_FIRST_MATCHES,
      commandStart: 0,
      commandEnd: 1,
      query: "",
    }),
    getSlashCommandSuggestions: () => LOCKED_FIRST_MATCHES,
  }),
}));

const { useSlashCommandDropdownState } = await import(
  "@/features/chat/hooks/useSlashCommandDropdownState"
);

function setup() {
  const onSlashCommandSelect = vi.fn();
  // getDropdownPosition bails on a null ref, which would leave the dropdown
  // inactive and make every assertion below vacuous.
  const textarea = document.createElement("textarea");
  document.body.appendChild(textarea);
  const inputRef = {
    current: textarea,
  } as React.RefObject<HTMLTextAreaElement | null>;

  const view = renderHook(() =>
    useSlashCommandDropdownState({
      inputRef,
      searchbarText: "/",
      onSearchbarTextChange: () => undefined,
      onSlashCommandSelect,
    }),
  );

  act(() => {
    view.result.current.updateSlashCommandDetection("/", 1);
  });
  expect(view.result.current.slashCommandState.isActive).toBe(true);

  return { view, onSlashCommandSelect };
}

function pressEnter(view: ReturnType<typeof setup>["view"]) {
  act(() => {
    view.result.current.handleSlashCommandKeyDown({
      key: "Enter",
      preventDefault: () => undefined,
    } as React.KeyboardEvent);
  });
}

describe("slash-command activation index space", () => {
  it("activates the row the keyboard actually highlighted when a locked tool sorts first", () => {
    const { view, onSlashCommandSelect } = setup();

    // One ArrowDown from the top. selectedIndex counts unlocked rows only, so
    // this highlights the SECOND unlocked tool (Deep Research) — the locked
    // Notion row is not part of that space.
    act(() => {
      view.result.current.navigateDown();
    });
    expect(view.result.current.slashCommandState.selectedIndex).toBe(1);

    pressEnter(view);

    // Indexing the full match list instead lands on index 1 = Web Search,
    // inserting a different tool than the one shown as selected.
    expect(onSlashCommandSelect).toHaveBeenCalledTimes(1);
    expect(onSlashCommandSelect).toHaveBeenCalledWith(
      "deep_research",
      "search",
    );
  });

  it("activates the first unlocked row when nothing has been navigated", () => {
    const { view, onSlashCommandSelect } = setup();

    pressEnter(view);

    // selectedIndex 0 is the first UNLOCKED row, not the locked row sitting at
    // full-list index 0 — full-list indexing selected nothing at all here.
    expect(onSlashCommandSelect).toHaveBeenCalledTimes(1);
    expect(onSlashCommandSelect).toHaveBeenCalledWith("web_search", "search");
  });
});
