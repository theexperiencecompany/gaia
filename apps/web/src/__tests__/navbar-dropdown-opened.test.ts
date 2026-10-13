// @vitest-environment jsdom
/**
 * navigation:navbar_dropdown_opened counts a menu opening, not the pointer
 * re-entering a trigger whose menu is already open.
 */
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNavbar } from "@/hooks/ui/useNavbar";
import { track } from "@/lib/analytics";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ email: "" }),
}));
vi.mock("@/hooks/useGitHubStars", () => ({
  useGitHubStars: () => ({ data: { stargazers_count: 100 } }),
}));
vi.mock("@/hooks/ui/useMediaQuery", () => ({ default: () => false }));
vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/" }));

const mockTrack = vi.mocked(track);

const hover = (): React.MouseEvent<HTMLButtonElement> =>
  ({
    currentTarget: document.createElement("button"),
  }) as unknown as React.MouseEvent<HTMLButtonElement>;

const opened = () =>
  mockTrack.mock.calls.filter(
    ([event]) => event === "navigation:navbar_dropdown_opened",
  );

describe("navbar dropdown analytics", () => {
  beforeEach(() => mockTrack.mockClear());

  it("counts one open while the pointer re-enters the same open menu", () => {
    const { result } = renderHook(() => useNavbar());

    act(() => result.current.handleMouseEnter("product", hover()));
    act(() => result.current.handleMouseEnter("product", hover()));
    act(() => result.current.handleMouseEnter("product", hover()));

    expect(opened()).toEqual([
      ["navigation:navbar_dropdown_opened", { menu: "product" }],
    ]);
  });

  it("counts a switch to another menu and a reopen after it closed", () => {
    const { result } = renderHook(() => useNavbar());

    act(() => result.current.handleMouseEnter("product", hover()));
    act(() => result.current.handleMouseEnter("resources", hover()));
    act(() => result.current.handleNavbarMouseLeave());
    act(() => result.current.handleMouseEnter("resources", hover()));

    expect(opened().map(([, props]) => props)).toEqual([
      { menu: "product" },
      { menu: "resources" },
      { menu: "resources" },
    ]);
  });
});
