/**
 * Spec-driven tests for genericLibrary.
 * Derived from the OpenUI Generic UI Architecture spec — does not read the
 * implementation to derive expected values.
 */
import { describe, expect, it } from "vitest";
import { genericLibrary } from "@/config/openui/genericLibrary";

// ---------------------------------------------------------------------------
// Spec-defined component groups and their members
// ---------------------------------------------------------------------------
const EXPECTED_GROUPS: Record<string, string[]> = {
  "Layout & Data": [
    "DataCard",
    "ResultList",
    "ComparisonTable",
    "StatusCard",
    "ActionCard",
    "TagGroup",
    "FileTree",
    "Accordion",
    "TabsBlock",
    "ProgressList",
    "SelectableList",
    "AvatarList",
    "KbdBlock",
  ],
  Analytics: [
    "StatRow",
    "BarChart",
    "LineChart",
    "AreaChart",
    "PieChart",
    "ScatterChart",
    "RadarChart",
    "GaugeChart",
  ],
  Content: [
    "ImageBlock",
    "ImageGallery",
    "VideoBlock",
    "AudioPlayer",
    "MapBlock",
    "CalendarMini",
    "NumberTicker",
    "Carousel",
    "TreeView",
  ],
  "Timeline & Notifications": ["Timeline", "AlertBanner", "Steps"],
  Code: ["CodeDiff"],
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

  it("contains exactly 36 components", () => {
    const count = Object.keys(genericLibrary.components).length;
    expect(count).toBe(36);
  });

  it("has exactly 5 component groups", () => {
    expect(genericLibrary.componentGroups).toBeDefined();
    expect(genericLibrary.componentGroups!.length).toBe(5);
  });

  it("has component groups with the exact expected names", () => {
    const groupNames = genericLibrary.componentGroups!.map((g) => g.name);
    expect(groupNames).toContain("Layout & Data");
    expect(groupNames).toContain("Analytics");
    expect(groupNames).toContain("Content");
    expect(groupNames).toContain("Timeline & Notifications");
    expect(groupNames).toContain("Code");
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
