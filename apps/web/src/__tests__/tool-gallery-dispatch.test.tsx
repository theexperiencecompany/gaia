// @vitest-environment jsdom
import { TOOL_FIXTURES } from "@shared/chat";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import ToolPage from "@/app/[locale]/dev/tool-gallery/[tool]/page.dev";

/**
 * The dev tool gallery routes each fixture to its card; only the tools with no
 * web card fall through to the "No web renderer" notice.
 */

let routeTool = "";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tool: routeTool }),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  usePathname: () => "/dev/tool-gallery",
  useRouter: () => ({ push: vi.fn() }),
}));

const UNSUPPORTED_ON_WEB = [
  "calendar_list_fetch_data",
  "connection_status_data",
  "memory_data",
  "tool_calls_data",
  "chart_data",
];

// Cards whose whole subtree renders without the app's provider stack.
const SELF_CONTAINED_CARDS = [
  "weather_data",
  "email_fetch_data",
  "reddit_data",
];

function renderRoute(toolName: string) {
  routeTool = toolName;
  return render(<ToolPage />);
}

describe("tool gallery dispatch", () => {
  it("lists exactly the fixtures the web has no card for", () => {
    const fixtureNames = TOOL_FIXTURES.map((f) => f.toolName);
    expect(fixtureNames).toEqual(expect.arrayContaining(UNSUPPORTED_ON_WEB));
  });

  it.each(UNSUPPORTED_ON_WEB)("shows the unsupported notice for %s", (name) => {
    renderRoute(name);
    expect(screen.getByText(/No web renderer for/).textContent).toBe(
      `No web renderer for ${name}`,
    );
  });

  it.each(SELF_CONTAINED_CARDS)("renders the card for %s", (name) => {
    renderRoute(name);
    expect(screen.queryByText(/No web renderer for/)).toBeNull();
    expect(screen.queryByText("Something went wrong!")).toBeNull();
  });

  it("names the route when no fixture matches", () => {
    renderRoute("not_a_tool");
    expect(screen.getByText(/Unknown tool:/).textContent).toBe(
      "Unknown tool: not_a_tool",
    );
  });
});
