// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RightSidebarPanel from "@/components/layout/sidebar/RightSidebarPanel";
import RightSidebarSlot, {
  RightSidebarSlotProvider,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { useLayoutStore } from "@/stores/layoutStore";

function renderPanel(ui: React.ReactNode) {
  return render(
    <RightSidebarSlotProvider>
      <RightSidebarSlot />
      {ui}
    </RightSidebarSlotProvider>,
  );
}

const rightSidebar = () => useLayoutStore.getState().rightSidebar;

describe("layoutStore right sidebar", () => {
  beforeEach(() => {
    useLayoutStore.setState({
      rightSidebar: { isOpen: false, mode: "sidebar" },
    });
  });

  it("starts closed", () => {
    expect(rightSidebar()).toEqual({ isOpen: false, mode: "sidebar" });
  });

  it("openRightSidebar sets the mode and closeRightSidebar keeps it", () => {
    useLayoutStore.getState().openRightSidebar("artifact");
    expect(rightSidebar()).toEqual({ isOpen: true, mode: "artifact" });

    // The mode survives the close so the outgoing panel animates out in the
    // chrome it opened in.
    useLayoutStore.getState().closeRightSidebar();
    expect(rightSidebar()).toEqual({ isOpen: false, mode: "artifact" });
  });

  it("stores no React element — only the open flag and mode", () => {
    useLayoutStore.getState().openRightSidebar("sheet");
    expect(Object.keys(rightSidebar()).sort()).toEqual(["isOpen", "mode"]);
  });
});

describe("RightSidebarPanel", () => {
  beforeEach(() => {
    useLayoutStore.setState({
      rightSidebar: { isOpen: false, mode: "sidebar" },
    });
  });

  it("opens the sidebar on mount and portals its children into the slot", () => {
    renderPanel(
      <RightSidebarPanel mode="sheet">
        <p>panel body</p>
      </RightSidebarPanel>,
    );

    expect(rightSidebar()).toEqual({ isOpen: true, mode: "sheet" });

    const body = screen.getByText("panel body");
    expect(body).toBeDefined();
    // Rendered into the layout's slot, not where the page mounted the panel.
    expect(body.closest("#right-sidebar-slot")).not.toBeNull();
  });

  it("closes the sidebar and removes its children on unmount", () => {
    const { unmount } = renderPanel(
      <RightSidebarPanel mode="sidebar">
        <p>panel body</p>
      </RightSidebarPanel>,
    );
    expect(rightSidebar().isOpen).toBe(true);

    unmount();

    expect(rightSidebar().isOpen).toBe(false);
    expect(screen.queryByText("panel body")).toBeNull();
  });

  it("calls onClose when the sidebar is closed externally (X button, Escape)", () => {
    const onClose = vi.fn();
    renderPanel(
      <RightSidebarPanel mode="sheet" onClose={onClose}>
        <p>panel body</p>
      </RightSidebarPanel>,
    );

    act(() => {
      useLayoutStore.getState().closeRightSidebar();
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when the panel itself unmounts", () => {
    const onClose = vi.fn();
    const { unmount } = renderPanel(
      <RightSidebarPanel mode="sheet" onClose={onClose}>
        <p>panel body</p>
      </RightSidebarPanel>,
    );

    unmount();

    expect(onClose).not.toHaveBeenCalled();
  });
});
