import { PassThrough } from "node:stream";
import { stripVTControlCharacters } from "node:util";
import { render } from "ink";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { LogWindow } from "../../src/ui/components/LogWindow.js";
import { fakeTerminal, tick } from "./fake-terminal.js";

const UP_ARROW = "\u001b[A";

function lines(count: number): string[] {
  return Array.from({ length: count }, (_, i) => `line ${i + 1}`);
}

/** The last frame Ink drew, as plain text. */
function lastFrame(written: string): string {
  const frames = stripVTControlCharacters(written).split("earlier line");
  return frames[frames.length - 1] ?? "";
}

/** A raw-mode terminal stdin the test can type into. */
function fakeKeyboard(): PassThrough {
  return Object.assign(new PassThrough(), {
    isTTY: true,
    setRawMode: () => undefined,
    ref: () => undefined,
    unref: () => undefined,
  });
}

describe("LogWindow", () => {
  it("scrolls up a line on the up arrow, then snaps to the newest lines when one arrives", async () => {
    const terminal = fakeTerminal(80, 30);
    const keyboard = fakeKeyboard();
    const app = render(createElement(LogWindow, { logs: lines(10) }), {
      stdout: terminal.stream as unknown as NodeJS.WriteStream,
      stdin: keyboard as unknown as NodeJS.ReadStream,
      patchConsole: false,
      debug: true,
    });
    await tick();
    expect(lastFrame(terminal.written())).toContain("line 10");

    keyboard.write(UP_ARROW);
    await tick();
    const scrolled = lastFrame(terminal.written());
    expect(scrolled).toContain("1 newer line");
    expect(scrolled).not.toContain("line 10");

    app.rerender(createElement(LogWindow, { logs: lines(11) }));
    await tick();
    const snapped = lastFrame(terminal.written());
    expect(snapped).toContain("line 11");
    expect(snapped).not.toContain("newer line");
    app.unmount();
  });
});
