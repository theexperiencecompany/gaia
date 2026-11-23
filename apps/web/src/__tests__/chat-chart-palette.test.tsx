// @vitest-environment jsdom
import { Renderer } from "@openuidev/react-lang";
import { ThemeProvider } from "@openuidev/react-ui/ThemeProvider";
import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { genericLibrary } from "@/config/openui/genericLibrary";
import { CHART_PALETTE, gaiaOpenUITheme } from "@/config/openui/theme";

/**
 * Regression: genui-lib's charts read a theme context bundled inside genui-lib, and react-ui's
 * theme has no chart palette keys, so every chat chart drew react-ui's light palette.
 */

// jsdom has no canvas; the charts measure tick labels with one.
beforeAll(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    font: "",
    measureText: (text: string) => ({ width: text.length * 6 }),
  } as unknown as CanvasRenderingContext2D);
});

function renderChat(code: string): string {
  const { container } = render(
    <ThemeProvider mode="dark" darkTheme={gaiaOpenUITheme}>
      <Renderer response={code} library={genericLibrary} />
    </ThemeProvider>,
  );
  return container.innerHTML.toLowerCase();
}

describe("chat OpenUI charts", () => {
  it.each([
    [
      "LineChart",
      'c = LineChart(["Mon", "Tue"], [Series("Sign-ups", [3, 5])])',
    ],
    ["BarChart", 'c = BarChart(["Mon", "Tue"], [Series("Sign-ups", [3, 5])])'],
    [
      "AreaChart",
      'c = AreaChart(["Mon", "Tue"], [Series("Sign-ups", [3, 5])])',
    ],
  ])(
    "%s draws its first series in the GAIA palette's first colour",
    (_, chart) => {
      const html = renderChat(`root = Stack([c])\n${chart}`);
      expect(html).toContain(CHART_PALETTE[0].toLowerCase());
    },
  );

  it("a two-series chart reads the palette in order", () => {
    const html = renderChat(
      'root = Stack([c])\nc = LineChart(["Mon", "Tue"], [Series("A", [3, 5]), Series("B", [4, 2])])',
    );
    const first = html.indexOf(CHART_PALETTE[0].toLowerCase());
    const second = html.indexOf(CHART_PALETTE[1].toLowerCase());
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(first);
  });

  it("charts take the app's dark surface, not react-ui's light default", () => {
    const html = renderChat(
      'root = Stack([c])\nc = LineChart(["Mon", "Tue"], [Series("Sign-ups", [3, 5])])',
    );
    expect(html).not.toContain("oklch(0.994 0 89.876");
  });
});
