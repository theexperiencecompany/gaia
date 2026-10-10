/**
 * How the right sidebar presents itself. This is the *presentation* axis — it
 * says nothing about which panel is inside, which is decided by whichever page
 * mounts a `<RightSidebarPanel>` and portals its content into the slot.
 *
 * - "sheet": modal overlay on top of the content (doesn't shift layout)
 * - "sidebar": persistent panel that pushes/shifts the main content layout
 * - "artifact": wide split-view panel optimised for file previewing
 */
export type RightSidebarMode = "sheet" | "sidebar" | "artifact";

export interface RightSidebarState {
  isOpen: boolean;
  mode: RightSidebarMode;
}
