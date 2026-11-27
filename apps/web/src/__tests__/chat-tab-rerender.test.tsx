// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { act, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ChatTab } from "@/components/layout/sidebar/ChatTab";

const dropdownRenders = vi.hoisted(() => ({ count: 0 }));

vi.mock("@/components/layout/sidebar/ChatOptionsDropdown", () => ({
  default: () => {
    dropdownRenders.count += 1;
    return null;
  },
}));

vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/c/other" }));

let rerenderSidebar: (() => void) | null = null;

function Sidebar() {
  const [, setTick] = useState(0);
  rerenderSidebar = () => setTick((tick) => tick + 1);
  return <ChatTab id="c1" name="Groceries" starred={false} />;
}

describe("ChatTab", () => {
  it("does not re-render when the sidebar re-renders with the same conversation", () => {
    render(<Sidebar />);
    const afterMount = dropdownRenders.count;

    act(() => rerenderSidebar?.());

    expect(dropdownRenders.count).toBe(afterMount);
  });
});
