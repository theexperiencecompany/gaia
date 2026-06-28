/**
 * Contract tests for genericLibrary.
 * The merged library combines `@openuidev/react-ui`'s base component set with
 * GAIA-only components. These assertions pin the public contract: the library
 * must exist, expose a non-empty components record that includes the names
 * below, and declare at least one component group.
 */
import { describe, expect, it } from "vitest";
import { genericLibrary } from "@/config/openui/genericLibrary";

const EXPECTED_COMPONENT_NAMES = [
  "Stack",
  "Card",
  "Table",
  "CardHeader",
  "Tag",
  "GaugeChart",
  "MapBlock",
  "Timeline",
  "FileTree",
  "TextDocument",
];

describe("genericLibrary", () => {
  it("is defined and truthy", () => {
    expect(genericLibrary).toBeTruthy();
  });

  it("has a non-empty components record", () => {
    expect(genericLibrary.components).toBeDefined();
    expect(typeof genericLibrary.components).toBe("object");
    expect(Object.keys(genericLibrary.components).length).toBeGreaterThan(0);
  });

  it.each(EXPECTED_COMPONENT_NAMES)('includes the "%s" component', (name) => {
    expect(genericLibrary.components[name]).toBeDefined();
  });

  it("declares at least one component group", () => {
    expect(genericLibrary.componentGroups).toBeDefined();
    expect(genericLibrary.componentGroups!.length).toBeGreaterThan(0);
  });
});
