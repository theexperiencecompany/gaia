import { Text } from "ink";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { useTerminalSize } from "../../src/ui/components/use-terminal-size.js";
import { renderOn, tick } from "./fake-terminal.js";

function Size() {
  const { columns, rows } = useTerminalSize();
  return createElement(Text, null, `${columns}x${rows}`);
}

describe("useTerminalSize", () => {
  it("re-renders with the new size when the terminal is resized", async () => {
    const { stream, written, app } = renderOn(createElement(Size), 100, 40, {
      debug: true,
    });

    stream.columns = 60;
    stream.rows = 24;
    stream.emit("resize");
    await tick();
    app.unmount();

    expect(written()).toContain("100x40");
    expect(written()).toContain("60x24");
  });

  it("assumes 80x24 on a terminal that reports no size", () => {
    const { written, app } = renderOn(createElement(Size), 0, 0, {
      debug: true,
    });
    app.unmount();

    expect(written()).toContain("80x24");
  });
});
