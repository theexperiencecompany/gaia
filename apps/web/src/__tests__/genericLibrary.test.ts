/**
 * Contract tests for genericLibrary.
 * The expected groups and members below are the library's public contract —
 * hardcoded (not derived by reading the implementation at runtime) so a drift
 * between the declared componentGroups and the registered components fails here.
 */
import { describe, expect, it } from "vitest";
import { genericLibrary } from "@/config/openui/genericLibrary";

// ---------------------------------------------------------------------------
// Spec-defined component groups and their members
// ---------------------------------------------------------------------------
const EXPECTED_GROUPS: Record<string, string[]> = {
  Primitives: [
    "TextContent",
    "CardHeader",
    "Tag",
    "TagBlock",
    "Callout",
    "Stat",
    "Col",
    "Table",
    "Button",
    "Buttons",
    "Progress",
    "Avatar",
    "Checkbox",
    "Radio",
  ],
  Layout: [
    "Stack",
    "Card",
    "Grid",
    "Row",
    "Column",
    "Separator",
    "CopyableContent",
    "FileTree",
    "Accordion",
    "TabsBlock",
    "KbdRow",
  ],
  Analytics: [
    "BarChart",
    "LineChart",
    "AreaChart",
    "PieChart",
    "ScatterChart",
    "RadarChart",
    "GaugeChart",
  ],
  Content: [
    "ImageGallery",
    "VideoBlock",
    "AudioPlayer",
    "MapBlock",
    "NumberTicker",
    "Carousel",
  ],
  Timeline: ["Timeline", "Steps"],
  Documents: ["TextDocument"],
};

const ALL_COMPONENT_NAMES = Object.values(EXPECTED_GROUPS).flat();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("genericLibrary", () => {
  it("is defined and truthy", () => {
    expect(genericLibrary).toBeTruthy();
  });

  it("has a components record", () => {
    expect(genericLibrary.components).toBeDefined();
    expect(typeof genericLibrary.components).toBe("object");
  });

  it("contains exactly 41 components", () => {
    const count = Object.keys(genericLibrary.components).length;
    expect(count).toBe(41);
  });

  it("has exactly 6 component groups", () => {
    expect(genericLibrary.componentGroups).toBeDefined();
    expect(genericLibrary.componentGroups!.length).toBe(6);
  });

  it("has component groups with the exact expected names", () => {
    const groupNames = genericLibrary.componentGroups!.map((g) => g.name);
    expect(groupNames).toContain("Primitives");
    expect(groupNames).toContain("Layout");
    expect(groupNames).toContain("Analytics");
    expect(groupNames).toContain("Content");
    expect(groupNames).toContain("Timeline");
    expect(groupNames).toContain("Documents");
  });

  it.each(
    Object.entries(EXPECTED_GROUPS),
  )('group "%s" has the correct component count', (groupName, expectedMembers) => {
    const group = genericLibrary.componentGroups!.find(
      (g) => g.name === groupName,
    );
    expect(group).toBeDefined();
    expect(group!.components.length).toBe(expectedMembers.length);
  });

  it.each(
    Object.entries(EXPECTED_GROUPS),
  )('group "%s" contains the correct component names', (groupName, expectedMembers) => {
    const group = genericLibrary.componentGroups!.find(
      (g) => g.name === groupName,
    );
    expect(group).toBeDefined();
    for (const name of expectedMembers) {
      expect(group!.components).toContain(name);
    }
  });

  it.each(
    ALL_COMPONENT_NAMES,
  )('component "%s" exists in the library', (name) => {
    expect(genericLibrary.components[name]).toBeDefined();
  });

  it.each(
    ALL_COMPONENT_NAMES,
  )('component "%s" has a non-empty name string', (name) => {
    const component = genericLibrary.components[name];
    expect(typeof component.name).toBe("string");
    expect(component.name.length).toBeGreaterThan(0);
  });

  it.each(
    ALL_COMPONENT_NAMES,
  )('component "%s" has a non-empty description string', (name) => {
    const component = genericLibrary.components[name];
    expect(typeof component.description).toBe("string");
    expect(component.description.length).toBeGreaterThan(0);
  });
});
