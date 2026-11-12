// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArtifactRenderer } from "../ArtifactRenderer";

const STATS = `root = Artifact("Launch", "How the week went", [], [s])
s = Section("Numbers", "The week", [n])
n = Stats([["Signups", "545", "Launch week"], ["Integration activations", "212", "Connected an app"], ["Retention", "61%", "Day 7"], ["Revenue", "$4.2k", "New MRR"]])`;

describe("artifact stat tiles", () => {
  // Regression: beside the open viewer the chat card squeezed four tiles into a narrow
  // column at the md breakpoint, splitting "Signups" and "545" mid-word.
  it("fit as many columns as the card has room for, not as many as the window does", () => {
    const { container } = render(<ArtifactRenderer program={STATS} />);
    const grid = container.querySelector('[data-slot="stats"]');

    expect(grid).not.toBeNull();
    expect(grid?.className).toContain("grid-cols-[repeat(auto-fit,minmax(");
    expect(grid?.className).not.toMatch(/\bmd:grid-cols-/);
  });
});
