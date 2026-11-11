// @vitest-environment jsdom
import { Button } from "@heroui/button";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RightSidebarSlot, {
  RightSidebarSlotProvider,
  usePanelDrawsClose,
} from "@/components/layout/sidebar/RightSidebarSlot";
import { useLayoutStore } from "@/stores/layoutStore";
import type { RightSidebarMode } from "@/stores/layoutStore.types";

function PanelHeader() {
  return usePanelDrawsClose() ? <Button aria-label="Close preview" /> : null;
}

function renderIn(mode: RightSidebarMode) {
  act(() => useLayoutStore.getState().openRightSidebar(mode));
  render(
    <RightSidebarSlotProvider>
      <RightSidebarSlot />
      <PanelHeader />
    </RightSidebarSlotProvider>,
  );
}

describe("who closes the right sidebar", () => {
  it.each<RightSidebarMode>(["sheet", "sidebar", "artifact"])(
    "draws exactly one close button in %s mode",
    (mode) => {
      renderIn(mode);

      expect(screen.getAllByRole("button", { name: /^Close/ })).toHaveLength(1);
    },
  );
});
