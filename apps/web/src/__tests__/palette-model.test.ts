/**
 * Unit tests for the palette's section builder (features/command/model/paletteModel.tsx).
 *
 * buildSections is the pure heart of the palette: given a view, query, and
 * data groups it decides every row the user sees. These pin the four view
 * levels (root / search / category / item), the always-present Ask GAIA row,
 * the server-result floor, loading state, and the frecency-boost contract.
 */
import { describe, expect, it } from "vitest";

import { buildSections, type Row } from "@/features/command/model/paletteModel";
import type { CommandGroup, CommandItem } from "@/features/command/model/types";

/** Minimal runnable row item. */
const item = (
  id: string,
  title: string,
  actions: CommandItem["actions"] = [],
): CommandItem => ({
  id,
  type: "action",
  title,
  icon: null,
  primary: { id: "run", label: title, icon: null, run: () => undefined },
  actions,
});

const group = (
  id: string,
  heading: string,
  items: CommandItem[],
  extra: Partial<CommandGroup> = {},
): CommandGroup => ({
  id,
  heading,
  accent: "text-zinc-400",
  kind: "entity",
  path: `/${id}`,
  items,
  ...extra,
});

const params = (over: Partial<Parameters<typeof buildSections>[0]>) => ({
  view: undefined,
  query: "",
  groups: [],
  recent: [],
  context: null,
  searchChats: [],
  searchMessages: [],
  searchMemories: [],
  searchLoading: false,
  ...over,
});

const titles = (rows: Row[]) =>
  rows.map((r) =>
    r.kind === "item"
      ? r.item.title
      : r.kind === "action"
        ? r.action.label
        : r.kind === "nav"
          ? r.label
          : r.id,
  );

describe("root level", () => {
  it("shows context first, recent next (minus the context item), then Browse + action groups", () => {
    const chatItem = item("chat:1", "Current chat");
    const sections = buildSections(
      params({
        context: { heading: "Current chat", item: chatItem },
        recent: [chatItem, item("todo:1", "A todo")],
        groups: [
          group("chats", "Chats", [chatItem]),
          item("cmd:new", "New chat") && {
            id: "actions",
            heading: "Quick actions",
            accent: "text-emerald-400",
            kind: "actions" as const,
            items: [item("cmd:new", "New chat")],
          },
        ],
      }),
    );

    expect(sections[0].heading).toBe("Current chat");
    expect(sections[1].heading).toBe("Recent");
    // The context item must not repeat inside Recent.
    expect(titles(sections[1].rows)).toEqual(["A todo"]);
    const browse = sections.find((s) => s.id === "browse");
    expect(browse).toBeDefined();
  });

  it("drops empty command groups but keeps empty entity categories browsable", () => {
    const sections = buildSections(
      params({
        groups: [
          {
            id: "actions",
            heading: "Quick actions",
            accent: "",
            kind: "actions",
            items: [],
          },
          group("workflows", "Workflows", []),
        ],
      }),
    );
    expect(sections.find((s) => s.id === "actions")).toBeUndefined();
    expect(sections.find((s) => s.id === "browse")).toBeDefined();
  });
});

describe("search level", () => {
  it("orders Jump-to above scored result sections and always ends with Ask GAIA", () => {
    const sections = buildSections(
      params({
        query: "workflows",
        groups: [
          group("workflows", "Workflows", [item("wf:1", "Deploy site")]),
          group("todos", "Todos", [item("td:1", "Buy milk")]),
        ],
      }),
    );
    expect(sections[0].heading).toBe("Jump to");
    expect(sections[sections.length - 1].rows[0].kind).toBe("ask");
  });

  it("keeps server hits with non-matching titles via the min-score floor", () => {
    const sections = buildSections(
      params({
        query: "meeting notes",
        searchChats: [item("chat:9", "Totally unrelated title")],
        groups: [group("chats", "Chats", [])],
      }),
    );
    const chats = sections.find((s) => s.id === "chats");
    expect(chats).toBeDefined();
  });

  it("renders a searching skeleton when loading with zero results", () => {
    const sections = buildSections(params({ query: "q", searchLoading: true }));
    const loading = sections.find((s) => s.id === "loading");
    expect(loading?.rows[0].kind).toBe("loading");
  });

  it("does not render the skeleton once results exist", () => {
    const sections = buildSections(
      params({
        query: "deploy",
        searchLoading: true,
        groups: [
          group("workflows", "Workflows", [item("wf:1", "Deploy site")]),
        ],
      }),
    );
    expect(sections.find((s) => s.id === "loading")).toBeUndefined();
  });

  it("dedupes server chats already present locally by id", () => {
    const local = item("chat:1", "Local copy");
    const sections = buildSections(
      params({
        query: "local",
        searchChats: [item("chat:1", "Server copy"), item("chat:2", "Other")],
        groups: [group("chats", "Chats", [local])],
      }),
    );
    const chats = sections.find((s) => s.id === "chats");
    const ids = chats
      ? chats.rows.map((r) => ("item" in r ? r.item.id : ""))
      : [];
    expect(ids.filter((id) => id === "chat:1")).toHaveLength(1);
  });

  it("frecency boost reorders equal-tier matches", () => {
    // Both titles prefix-match "deploy" identically (90 * 2 = 180); only the
    // boost differs.
    const sections = buildSections(
      params({
        query: "deploy",
        groups: [
          group("workflows", "Workflows", [
            item("wf:plain", "Deploy site"),
            item("wf:fav", "Deploy api"),
          ]),
        ],
        boost: (i) => (i.id === "wf:fav" ? 10 : 0),
      }),
    );
    expect(titles(sections[0].rows)[0]).toBe("Deploy api");
  });

  it("boost cannot outrank a strictly better match tier", () => {
    // Max realistic frecency is score 10 * multiplier 3 = 30. A word-boundary
    // title match (80 * 2 = 160) must still beat a keyword-only match
    // (~40-ish + 30).
    const sections = buildSections(
      params({
        query: "todo",
        groups: [
          group("things", "Things", [
            {
              ...item("a:weak", "Unrelated title"),
              keywords: "todo stuff",
            },
            item("b:strong", "Todo"),
          ]),
        ],
        boost: () => 30,
      }),
    );
    expect(titles(sections[0].rows)[0]).toBe("Todo");
  });
});

describe("category level", () => {
  it("shows Go back, Go-to and links when the query is empty; filters everything by query otherwise", () => {
    const sections = buildSections(
      params({
        view: { level: "category", groupId: "todos" },
        query: "",
        groups: [
          group(
            "todos",
            "Todos",
            [item("td:1", "Buy milk"), item("td:2", "Walk dog")],
            { links: [{ label: "Today", path: "/todos/today" }] },
          ),
        ],
      }),
    );
    const labels = titles(sections[0].rows);
    expect(labels).toEqual([
      "back",
      "Go to Todos",
      "Today",
      "Buy milk",
      "Walk dog",
    ]);

    // A query that matches nothing but one item drops nav rows too.
    const filtered = buildSections(
      params({
        view: { level: "category", groupId: "todos" },
        query: "walk",
        groups: [
          group(
            "todos",
            "Todos",
            [item("td:1", "Buy milk"), item("td:2", "Walk dog")],
            { links: [{ label: "Today", path: "/todos/today" }] },
          ),
        ],
      }),
    );
    expect(titles(filtered[0].rows)).toEqual(["back", "Walk dog"]);
  });
});

describe("item level", () => {
  it("lists the item's actions after Go back, filtered by query", () => {
    const target = item("chat:1", "My chat", [
      { id: "rename", label: "Rename", icon: null, run: () => undefined },
      { id: "star", label: "Star chat", icon: null, run: () => undefined },
      {
        id: "delete",
        label: "Delete chat",
        icon: null,
        destructive: true,
        run: () => undefined,
      },
    ]);
    const sections = buildSections(
      params({
        view: { level: "item", item: target },
        query: "rename",
      }),
    );
    const labels = titles(sections[0].rows);
    expect(labels).toEqual(["back", "Rename"]);
  });
});
