// @vitest-environment jsdom

import type { ProjectResponse, TodoCardData } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TodoSection from "./TodoSection";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => null,
}));
vi.mock("@/stores/todoStore", () => ({ useTodoStore: () => vi.fn() }));

const EMPTY_CARD: TodoCardData = {
  action: "list",
  message: "",
  todos: null,
  projects: null,
  project_completion: null,
  stats: null,
  counts: null,
  summary: null,
};

const PROJECT: ProjectResponse = {
  id: "proj-1",
  user_id: "u1",
  name: "Work",
  description: null,
  color: null,
  is_default: false,
  todo_count: 4,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

describe("TodoSection", () => {
  it("shows the server's today and upcoming counts beside the stats", () => {
    render(
      <TodoSection
        card={{
          ...EMPTY_CARD,
          action: "stats",
          stats: { total: 10, completed: 5, pending: 5, overdue: 0 },
          counts: { inbox: 1, today: 2, upcoming: 3, completed: 5, overdue: 0 },
        }}
      />,
    );

    expect(screen.getByText("Today").previousSibling?.textContent).toBe("2");
    expect(screen.getByText("Soon").previousSibling?.textContent).toBe("3");
  });

  it("leaves the tiles out when a stored card carries no counts", () => {
    render(
      <TodoSection
        card={{
          ...EMPTY_CARD,
          action: "stats",
          stats: { total: 1, completed: 0, pending: 1, overdue: 0 },
        }}
      />,
    );

    expect(screen.queryByText("Today")).toBeNull();
    expect(screen.queryByText("Soon")).toBeNull();
  });

  it("shows each project's completion the server computed", () => {
    render(
      <TodoSection
        card={{
          ...EMPTY_CARD,
          projects: [PROJECT],
          project_completion: { "proj-1": 75 },
        }}
      />,
    );

    expect(screen.getByText("75%")).toBeDefined();
  });
});
